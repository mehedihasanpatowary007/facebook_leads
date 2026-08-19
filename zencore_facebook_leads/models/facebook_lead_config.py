import logging
from urllib.parse import urljoin

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FacebookLeadConfig(models.Model):
    _name = "facebook.lead.config"
    _description = "Facebook Lead Integration"
    _order = "company_id, name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    page_name = fields.Char(string="Facebook Page Name")
    page_id = fields.Char(string="Facebook Page ID", required=True, index=True)
    app_id = fields.Char(string="Meta App ID")
    app_secret = fields.Char(groups="sales_team.group_sale_manager", copy=False)
    page_access_token = fields.Char(required=True, groups="sales_team.group_sale_manager", copy=False)
    verify_token = fields.Char(required=True, groups="sales_team.group_sale_manager", copy=False)
    api_version = fields.Char(string="Graph API Version", default="v25.0", required=True)
    validate_signature = fields.Boolean(default=True)
    default_team_id = fields.Many2one("crm.team", string="Default Sales Team")
    default_user_id = fields.Many2one("res.users", string="Default Salesperson")
    default_source_id = fields.Many2one("utm.source", default=lambda self: self.env.ref("zencore_facebook_leads.utm_source_facebook", raise_if_not_found=False))
    default_medium_id = fields.Many2one("utm.medium", default=lambda self: self.env.ref("zencore_facebook_leads.utm_medium_facebook_lead_ads", raise_if_not_found=False))
    auto_sync = fields.Boolean(default=True)
    sync_interval = fields.Selection([("15", "15 Minutes"), ("30", "30 Minutes"), ("60", "1 Hour")], default="15", required=True)
    last_sync_at = fields.Datetime(readonly=True)
    webhook_url = fields.Char(compute="_compute_webhook_url")
    mapping_ids = fields.One2many("facebook.lead.mapping", "config_id")
    campaign_mapping_ids = fields.One2many("facebook.campaign.mapping", "config_id")

    _page_company_unique = models.Constraint(
        "UNIQUE(page_id, company_id)", "This Facebook Page is already configured for this company."
    )

    @api.constrains("validate_signature", "app_secret")
    def _check_signature_config(self):
        for record in self:
            if record.validate_signature and not record.app_secret:
                raise ValidationError("Meta App Secret is required when signature validation is enabled.")

    @api.depends("page_id")
    def _compute_webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for record in self:
            record.webhook_url = urljoin(base.rstrip("/") + "/", "meta_lead_ads/webhook") if base else "/meta_lead_ads/webhook"

    def _graph_get(self, object_id, params=None):
        self.ensure_one()
        clean_version = self.api_version.strip().strip("/")
        url = urljoin("https://graph.facebook.com/%s/" % clean_version, str(object_id).strip("/"))
        safe_params = dict(params or {})
        safe_params["access_token"] = self.page_access_token
        try:
            response = requests.get(url, params=safe_params, timeout=30)
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(_("Meta API is unavailable: %s") % exc) from exc
        except ValueError as exc:
            raise UserError(_("Meta API returned an invalid response.")) from exc
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error") or {}
            raise UserError(_("Meta API error: %s") % (error.get("message") or response.reason))
        return payload

    def action_test_connection(self):
        self.ensure_one()
        payload = self._graph_get(self.page_id, {"fields": "id,name"})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Connection Successful"), "message": payload.get("name") or payload.get("id"), "type": "success"
        }}

    @api.model
    def _cron_backup_sync(self):
        now = fields.Datetime.now()
        for config in self.sudo().search([("active", "=", True), ("auto_sync", "=", True)]):
            interval = int(config.sync_interval or 15)
            if config.last_sync_at and (now - config.last_sync_at).total_seconds() < interval * 60:
                continue
            try:
                config._backup_sync()
                config.last_sync_at = now
            except Exception:
                _logger.exception("Facebook backup sync failed for configuration %s", config.id)

    def _backup_sync(self):
        self.ensure_one()
        forms_url = self.page_id + "/leadgen_forms"
        forms = self._graph_get(forms_url, {"fields": "id,name", "limit": 100}).get("data", [])
        for form in forms:
            payload = self._graph_get(form["id"] + "/leads", {
                "fields": "id,created_time,field_data,form_id,ad_id,campaign_id,campaign_name", "limit": 100
            })
            for lead_data in payload.get("data", []):
                lead_id = str(lead_data.get("id") or "")
                if not lead_id or self.env["facebook.lead.log"].sudo().search_count([("facebook_lead_id", "=", lead_id)]):
                    continue
                log = self.env["facebook.lead.log"].sudo().create({
                    "config_id": self.id, "facebook_lead_id": lead_id,
                    "facebook_form_id": str(form["id"]), "facebook_form_name": form.get("name"),
                    "raw_reference": lead_data, "status": "pending",
                })
                log._process(lead_data=lead_data)
        return True
