# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    ip_call_active = fields.Boolean(
        string='IP Call Active',
        compute='_compute_ip_call_active',
    )

    def _compute_ip_call_active(self):
        active_history = self.env['zencore.wub.ip.call.history'].search([
            ('lead_id', 'in', self.ids),
            ('user_id', '=', self.env.user.id),
            ('operation_type', '=', 'click_to_call'),
            ('state', '=', 'success'),
            ('is_active_call', '=', True),
        ])
        active_lead_ids = set(active_history.mapped('lead_id').ids)
        for lead in self:
            lead.ip_call_active = lead.id in active_lead_ids

    def action_ip_call_hangup(self):
        self.ensure_one()
        return self.env['zencore.wub.ip.call.history'].send_call_hangup(self)

    def unlink(self):
        """Release the local call lock before its lead reference is removed.

        The history model keeps records when a lead is deleted by setting
        ``lead_id`` to null. Without this cleanup, a successful call remains
        active forever and blocks the user from starting another call.
        """
        active_calls = self.env['zencore.wub.ip.call.history'].sudo().search([
            ('lead_id', 'in', self.ids),
            ('operation_type', '=', 'click_to_call'),
            ('state', '=', 'success'),
            ('is_active_call', '=', True),
        ])
        result = super().unlink()
        if active_calls.exists():
            active_calls.write({'is_active_call': False})
            _logger.info(
                'Released %s active WUB IP call(s) after deleting CRM lead(s) %s.',
                len(active_calls),
                self.ids,
            )
        return result
