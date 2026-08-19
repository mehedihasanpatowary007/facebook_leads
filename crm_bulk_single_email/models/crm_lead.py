from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def write(self, vals):
        old_user_ids = {lead.id: lead.user_id.id for lead in self}
        result = super().write(vals)

        if 'user_id' not in vals or not vals.get('user_id'):
            return result

        new_user_id = vals['user_id']
        assigned_leads = self.filtered(
            lambda l: l.user_id.id == new_user_id and
                      old_user_ids.get(l.id) != new_user_id
        )

        if assigned_leads:
            new_user = self.env['res.users'].browse(new_user_id)
            if new_user.email:
                self._send_bulk_assignment_email(new_user, assigned_leads)

        return result

    def _message_auto_subscribe_notify(self, partner_ids, template):
        """
        Block Odoo's default one-by-one assignment emails for CRM leads.
        template is a string (xml_id) in Odoo 19.
        """
        # template is a string like 'crm.mail_template_crm_lead_assigned'
        template_str = template if isinstance(template, str) else getattr(template, 'xml_id', '') or ''
        if 'crm' in template_str or 'assigned' in template_str:
            _logger.info("Blocked default CRM assignment email (template: %s).", template_str)
            return
        return super()._message_auto_subscribe_notify(partner_ids, template)

    def _notify_salesperson_assignment(self, salesperson, leads=None):
        """Block Odoo 19 built-in salesperson assignment notification."""
        return True

    def _send_bulk_assignment_email(self, user, leads):
        """Send ONE single email listing all assigned leads."""
        lead_count = len(leads)
        lead_names = ', '.join(leads.mapped('name'))

        subject = f'You have been assigned to {lead_count} lead{"s" if lead_count > 1 else ""}'

        body_html = f"""
        <div style="font-family:Arial,sans-serif;font-size:14px;color:#333;max-width:600px;padding:24px;">
            <p>Dear <strong>{user.name}</strong>,</p>
            <p>You have been assigned to <strong>{lead_count} lead{"s" if lead_count > 1 else ""}</strong>: {lead_names}.</p>
            <p>Please review & Take care of them..</p>
            <p style="color:#999;font-size:12px;margin-top:24px;border-top:1px solid #eee;padding-top:12px;">
                This is an automated notification from your CRM system.
            </p>
        </div>
        """

        company = self.env.company
        from_email = company.email or self.env.user.email or 'noreply@example.com'

        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_to': user.email,
            'email_from': from_email,
            'auto_delete': False,
            'state': 'outgoing',
        }

        try:
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.sudo().send()
            _logger.info("Bulk assignment email sent to %s for %d leads.", user.email, lead_count)
        except Exception as e:
            _logger.error("Failed to send bulk assignment email: %s", str(e))