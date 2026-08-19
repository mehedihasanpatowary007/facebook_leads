from odoo import _, fields, models
from odoo.exceptions import UserError


class FacebookLeadForm(models.Model):
    _name = "facebook.lead.form"
    _description = "Facebook Lead Form"
    _order = "config_id, name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    config_id = fields.Many2one("facebook.lead.config", required=True, ondelete="cascade")
    facebook_form_id = fields.Char(string="Facebook Form ID", required=True, index=True)
    status = fields.Char(readonly=True)
    last_refreshed_at = fields.Datetime(readonly=True)
    last_error_message = fields.Text(readonly=True)
    mapping_ids = fields.One2many("facebook.lead.mapping", "form_id", string="Field Mapping")
    mapping_count = fields.Integer(compute="_compute_mapping_count")

    _form_config_unique = models.Constraint(
        "UNIQUE(config_id, facebook_form_id)", "This Facebook Form is already imported for this Page."
    )

    def _compute_mapping_count(self):
        for record in self:
            record.mapping_count = len(record.mapping_ids)

    def action_refresh_fields(self):
        failures = 0
        for record in self:
            try:
                record.config_id._import_form_questions(record)
                record.write({"last_refreshed_at": fields.Datetime.now(), "last_error_message": False})
            except UserError as exc:
                record.write({"last_error_message": str(exc)[:2000]})
                failures += 1
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Form Field Refresh"),
            "message": _("Field refresh completed; %(failed)s form(s) require attention.", failed=failures),
            "type": "warning" if failures else "success",
        }}

    def action_sync_leads(self):
        for record in self:
            record.config_id._sync_single_form(record, full=True)
        cron = self.env.ref("zencore_facebook_leads.ir_cron_facebook_process_queue", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Lead Sync Complete"), "message": _("Accessible leads were queued for CRM processing."), "type": "success"
        }}
