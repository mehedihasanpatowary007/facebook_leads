# -*- coding: utf-8 -*-
from odoo import _, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    ip_call_history_ids = fields.One2many(
        'zencore.wub.ip.call.history',
        'lead_id',
        string='IP Call History',
        readonly=True,
    )
    ip_call_history_count = fields.Integer(
        string='IP Call Count',
        compute='_compute_ip_call_history_count',
    )
    def _compute_ip_call_history_count(self):
        grouped_data = self.env['zencore.wub.ip.call.history'].read_group(
            domain=[('lead_id', 'in', self.ids)],
            groupby=['lead_id'],
            fields=['lead_id'],
        )
        mapped_count = {
            item['lead_id'][0]: item.get('lead_id_count', item.get('__count', 0))
            for item in grouped_data
            if item.get('lead_id')
        }
        for lead in self:
            lead.ip_call_history_count = mapped_count.get(lead.id, 0)

    def action_ip_call(self):
        self.ensure_one()
        return self.env['zencore.wub.ip.call.history'].send_click_to_call(self)

    def action_view_ip_call_history(self):
        self.ensure_one()
        action = self.env.ref('zencore_wub_ipcalling.action_wub_ip_call_history').read()[0]
        action['domain'] = [('lead_id', '=', self.id)]
        action['context'] = {
            'default_lead_id': self.id,
            'search_default_lead_id': self.id,
        }
        action['display_name'] = _('IP Call History - %s') % (self.display_name,)
        return action
