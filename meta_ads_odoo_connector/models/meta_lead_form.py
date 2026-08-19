# -*- coding: utf-8 -*-
from odoo import models, fields, _


class MetaLeadForm(models.Model):
    _name = 'meta.lead.form'
    _description = 'Meta Lead Form Mapping'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', ondelete='set null', index=True)

    meta_form_id = fields.Char(required=True, index=True)
    meta_page_id = fields.Char(index=True)
    page_name = fields.Char()
    crm_team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Assigned Salesperson')
    tag_ids = fields.Many2many('crm.tag', string='CRM Tags')
    field_mapping_json = fields.Json(default=lambda self: {
        'full_name': 'contact_name',
        'email': 'email_from',
        'phone_number': 'phone',
        'city': 'city',
    })
    last_import_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    # _sql_constraints = [
    #     ('meta_lead_form_company_unique', 'unique(company_id, meta_form_id)', 'This Meta lead form already exists for this company.'),
    # ]

    def action_import_latest_leads(self):
        """Placeholder for production Lead Ads import.

        Lead retrieval normally requires page/leadgen permissions and a valid page token.
        Keep this method as the safe extension point for webhook or polling implementation.
        """
        for rec in self:
            rec.message_post(body=_('Lead import endpoint is ready. Connect Meta Lead Ads webhook or polling logic here.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Meta Lead Forms'),
                'message': _('Lead import placeholder executed. Implement webhook/polling with your approved Meta app permissions.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def create_crm_lead_from_payload(self, payload):
        """Create a crm.lead from normalized Meta lead payload.

        Expected payload example:
        {
            'id': 'leadgen_id',
            'created_time': '2026-06-24T10:00:00+0000',
            'field_data': [{'name': 'email', 'values': ['a@example.com']}]
        }
        """
        self.ensure_one()
        field_values = {}
        for item in payload.get('field_data', []):
            values = item.get('values') or []
            field_values[item.get('name')] = values[0] if values else False

        mapping = self.field_mapping_json or {}
        vals = {
            'name': _('Meta Lead - %s') % (field_values.get('full_name') or field_values.get('email') or payload.get('id')),
            'team_id': self.crm_team_id.id or False,
            'user_id': self.user_id.id or False,
            'company_id': self.company_id.id,
            'x_meta_leadgen_id': payload.get('id'),
            'x_meta_form_id': self.meta_form_id,
            'x_meta_page_id': self.meta_page_id,
            'x_meta_created_time': payload.get('created_time'),
            'x_meta_raw_payload': payload,
        }
        for meta_field, odoo_field in mapping.items():
            if odoo_field and meta_field in field_values:
                vals[odoo_field] = field_values[meta_field]

        lead = self.env['crm.lead'].sudo().create(vals)
        if self.tag_ids:
            lead.tag_ids = [(4, tag.id) for tag in self.tag_ids]
        return lead
