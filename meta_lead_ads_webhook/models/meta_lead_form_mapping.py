# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MetaLeadFormMapping(models.Model):
    _name = 'meta.lead.form.mapping'
    _description = 'Meta Lead Form Mapping'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        related='connection_id.company_id',
        store=True,
        readonly=True,
    )
    connection_id = fields.Many2one(
        'meta.lead.connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    meta_form_id = fields.Char(string='Meta Form ID', required=True, index=True)
    meta_form_name = fields.Char(string='Meta Form Name')

    crm_team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Salesperson')
    source_id = fields.Many2one('utm.source', string='UTM Source')
    medium_id = fields.Many2one('utm.medium', string='UTM Medium')
    campaign_id = fields.Many2one('utm.campaign', string='UTM Campaign')
    tag_ids = fields.Many2many('crm.tag', string='CRM Tags')

    field_map_line_ids = fields.One2many(
        'meta.lead.form.field.map',
        'mapping_id',
        string='Custom Field Mapping',
    )

    # _sql_constraints = [
    #     ('form_connection_unique', 'unique(connection_id, meta_form_id)', 'This form is already mapped for this connection.'),
    # ]

    def get_target_values(self):
        self.ensure_one()
        return {
            'team_id': self.crm_team_id.id or self.connection_id.default_team_id.id or False,
            'user_id': self.user_id.id or self.connection_id.default_user_id.id or False,
            'source_id': self.source_id.id or self.connection_id.default_source_id.id or False,
            'medium_id': self.medium_id.id or self.connection_id.default_medium_id.id or False,
            'campaign_id': self.campaign_id.id or False,
            'tag_ids': [(6, 0, (self.tag_ids or self.connection_id.default_tag_ids).ids)],
        }


class MetaLeadFormFieldMap(models.Model):
    _name = 'meta.lead.form.field.map'
    _description = 'Meta Lead Form Field Mapping'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    mapping_id = fields.Many2one(
        'meta.lead.form.mapping',
        required=True,
        ondelete='cascade',
    )
    meta_field_name = fields.Char(
        required=True,
        help='Exact field name returned by Meta, for example: custom_question, city, product_interest.',
    )
    odoo_field_name = fields.Char(
        required=True,
        help='Technical field name on crm.lead, for example: x_product_interest.',
    )

    def action_validate_field(self):
        lead_fields = self.env['crm.lead']._fields
        for rec in self:
            if rec.odoo_field_name not in lead_fields:
                raise UserError(_('Field %s does not exist on crm.lead.') % rec.odoo_field_name)
        return True
