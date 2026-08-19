from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FacebookLeadMapping(models.Model):
    _name = "facebook.lead.mapping"
    _description = "Facebook Lead Field Mapping"
    _order = "config_id, facebook_form_id, sequence, id"

    sequence = fields.Integer(default=10)
    config_id = fields.Many2one("facebook.lead.config", required=True, ondelete="cascade")
    facebook_form_id = fields.Char(required=True, index=True)
    facebook_form_name = fields.Char()
    facebook_field_name = fields.Char(required=True)
    odoo_field_id = fields.Many2one(
        "ir.model.fields", required=True, ondelete="cascade",
        domain="[('model', '=', 'crm.lead'), ('store', '=', True), ('readonly', '=', False), ('ttype', 'in', ('char', 'text', 'html', 'selection', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime', 'many2one'))]",
    )
    required = fields.Boolean()
    active = fields.Boolean(default=True)

    _mapping_unique = models.Constraint(
        "UNIQUE(config_id, facebook_form_id, facebook_field_name)",
        "A Facebook field can only be mapped once per form and configuration.",
    )

    @api.constrains("odoo_field_id")
    def _check_target_field(self):
        protected = {"id", "facebook_lead_id", "facebook_page_id", "facebook_form_id", "facebook_config_id"}
        for record in self:
            target = record.odoo_field_id
            if target.model != "crm.lead" or target.name in protected or target.readonly or not target.store:
                raise ValidationError("Select a stored, writable CRM Lead field.")
