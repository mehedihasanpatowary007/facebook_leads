from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    rr_last_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Last Assigned (Round Robin)',
        copy=False,
    )

    #  Odoo built-in Rule-Based Assignment Cron 
    def _action_assign_leads(self, work_days=False, **kwargs):
        teams = self if self.ids else self.search([
            ('active', '=', True),
            ('assignment_optout', '=', False),
        ])
        for team in teams:
            assigned, merged = team._assign_unassigned_leads_round_robin()
            msg = (
                f'Round Robin (Auto): {assigned} lead(s) assigned. '
                f'{team.rr_last_user_id.name or "N/A"}'
            )
            if merged:
                msg += f' | {merged} duplicate(s) merged.'
            if assigned or merged:
                team.sudo().message_post(body=msg)

    #  Manual "Assign Leads" Button 
    def action_assign_leads(self):
        total_assigned = 0
        total_merged = 0

        for team in self:
            assigned, merged = team._assign_unassigned_leads_round_robin()
            msg = (
                f'Round Robin (Manual): {assigned} lead(s) assigned. '
                f'{team.rr_last_user_id.name or "N/A"}'
            )
            if merged:
                msg += f' | {merged} duplicate(s) merged.'
            team.sudo().message_post(body=msg)
            total_assigned += assigned
            total_merged += merged

        notif_msg = f'{total_assigned} lead(s) assigned successfully.'
        if total_merged:
            notif_msg += f' {total_merged} duplicate(s) merged.'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Round Robin Assignment',
                'message': notif_msg,
                'type': 'success' if total_assigned else 'warning',
                'sticky': False,
            },
        }

    def _merge_duplicate_leads(self, leads):
        self.ensure_one()

        email_groups = {}
        no_email_leads = self.env['crm.lead']

        for lead in leads:
            email = (lead.email_from or '').strip().lower()

            if not email:
                no_email_leads |= lead
                continue

            if email not in email_groups:
                email_groups[email] = self.env['crm.lead']

            email_groups[email] |= lead

        unique_leads = self.env['crm.lead']
        merged_count = 0

        # keep non-email leads
        unique_leads |= no_email_leads

        for email, group in email_groups.items():

            # single lead
            if len(group) == 1:
                unique_leads |= group
                continue

            sorted_group = group.sorted(key=lambda l: l.id)

            master = sorted_group[0]
            duplicates = sorted_group[1:]

            _logger.info(
                'RR Merge: team "%s" | email="%s" | master=id:%s | duplicates=%s',
                self.name,
                email,
                master.id,
                duplicates.ids,
            )

            try:
                all_leads = master | duplicates

                wizard = self.env['crm.merge.opportunity'].sudo().create({
                    'opportunity_ids': [(6, 0, all_leads.ids)],
                })

                wizard.action_merge()

                # IMPORTANT
                # reload surviving merged lead
                surviving_lead = self.env['crm.lead'].sudo().browse(master.id)

                if surviving_lead.exists() and surviving_lead.active:
                    unique_leads |= surviving_lead

                merged_count += len(duplicates)

            except Exception as e:

                _logger.warning(
                    'RR Merge failed (%s). Archiving duplicates.',
                    e
                )

                duplicates.sudo().write({
                    'active': False
                })

                unique_leads |= master

        return unique_leads.filtered(lambda l: l.exists() and l.active), merged_count
    # Team Members 
    def _get_ordered_team_users(self):
        self.ensure_one()
        members = self.env['crm.team.member'].search([
            ('crm_team_id', '=', self.id),
            ('active', '=', True),
        ], order='id asc')

        ordered_users = []
        seen_ids = set()
        for member in members:
            user = member.user_id
            if user and user.active and user.id not in seen_ids:
                ordered_users.append(user)
                seen_ids.add(user.id)
        return ordered_users

    #  Core Round Robin Logic 
    def _assign_unassigned_leads_round_robin(self):
        """Returns (assigned_count, merged_count)"""
        self.ensure_one()

        active_users = self._get_ordered_team_users()
        if not active_users:
            _logger.info('RR: team "%s" — no active members.', self.name)
            return 0, 0

        # Assignment domain parse
        raw_domain = self.assignment_domain
        if not raw_domain:
            team_domain = []
        elif isinstance(raw_domain, (list, tuple)):
            team_domain = list(raw_domain)
        elif isinstance(raw_domain, str):
            try:
                team_domain = safe_eval(raw_domain)
            except Exception:
                _logger.warning('RR: domain parse failed for "%s".', self.name)
                team_domain = []
        else:
            team_domain = []

        base_domain = [
            ('user_id', '=', False),
            ('active', '=', True),
            '|',
            ('team_id', '=', self.id),
            ('team_id', '=', False),
        ]
        leads = self.env['crm.lead'].search(
            base_domain + team_domain, order='id asc'
        )

        if not leads:
            _logger.info('RR: team "%s" — no unassigned leads.', self.name)
            return 0, 0

        # duplicate merge then assign
        #leads, merged_count = self._merge_duplicate_leads(leads)

        merged_count = 0

        # Starting index
        last_user = self.rr_last_user_id
        user_ids_list = [u.id for u in active_users]

        if not last_user or last_user.id not in user_ids_list:
            current_index = 0
        else:
            last_index = user_ids_list.index(last_user.id)
            current_index = (last_index + 1) % len(active_users)

        _logger.info(
            'RR: team "%s" | members=%s | leads=%s | start="%s"',
            self.name,
            [u.name for u in active_users],
            len(leads),
            active_users[current_index].name,
        )

        assigned_count = 0
        last_assigned_user = None

        for lead in leads:
            user = active_users[current_index]
            lead.sudo().write({
                'user_id': user.id,
                'team_id': self.id,
                'type': 'opportunity',
            })
            last_assigned_user = user
            _logger.info('RR: "%s" → "%s"', lead.name, user.name)
            assigned_count += 1
            current_index = (current_index + 1) % len(active_users)

        if last_assigned_user:
            self.sudo().write({'rr_last_user_id': last_assigned_user.id})

        return assigned_count, merged_count