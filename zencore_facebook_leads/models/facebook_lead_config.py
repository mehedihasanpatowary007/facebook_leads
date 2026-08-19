import logging
from datetime import timezone
from urllib.parse import urljoin

import requests
from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FacebookLeadConfig(models.Model):
    _name = "facebook.lead.config"
    _description = "Facebook Lead Integration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
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
    webhook_url = fields.Char(
        string="Webhook URL",
        default="https://wub-support-demo-34686622.dev.odoo.com/meta_lead_ads/webhook",
        required=True,
        help="Public HTTPS callback registered in the Meta application.",
    )
    default_team_id = fields.Many2one("crm.team", string="Default Sales Team")
    default_user_id = fields.Many2one("res.users", string="Default Salesperson")
    default_source_id = fields.Many2one("utm.source", default=lambda self: self.env.ref("zencore_facebook_leads.utm_source_facebook", raise_if_not_found=False))
    default_medium_id = fields.Many2one("utm.medium", default=lambda self: self.env.ref("zencore_facebook_leads.utm_medium_facebook_lead_ads", raise_if_not_found=False))
    auto_sync = fields.Boolean(default=True)
    full_sync_requested = fields.Boolean(readonly=True, copy=False)
    sync_interval = fields.Selection([("15", "15 Minutes"), ("30", "30 Minutes"), ("60", "1 Hour")], default="15", required=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_webhook_at = fields.Datetime(readonly=True)
    last_success_at = fields.Datetime(readonly=True)
    last_error_at = fields.Datetime(readonly=True)
    last_error_message = fields.Text(readonly=True)
    consecutive_failures = fields.Integer(readonly=True)
    max_retry_count = fields.Integer(default=5, required=True)
    retry_delay_minutes = fields.Integer(default=5, required=True)
    processing_batch_size = fields.Integer(default=50, required=True)
    log_retention_days = fields.Integer(default=180, required=True)
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

    @api.constrains("webhook_url")
    def _check_webhook_url(self):
        for record in self:
            if not record.webhook_url.startswith("https://") or not record.webhook_url.rstrip("/").endswith("/meta_lead_ads/webhook"):
                raise ValidationError(_("Webhook URL must use HTTPS and end with /meta_lead_ads/webhook."))

    @api.constrains("max_retry_count", "retry_delay_minutes", "processing_batch_size", "log_retention_days")
    def _check_positive_settings(self):
        for record in self:
            if min(record.max_retry_count, record.retry_delay_minutes, record.processing_batch_size, record.log_retention_days) <= 0:
                raise ValidationError(_("Retry, batch, and retention settings must be greater than zero."))

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
            raise UserError(
                _("Meta API error [code %(code)s]: %(message)s", code=error.get("code") or response.status_code, message=error.get("message") or response.reason)
            )
        return payload

    def action_test_connection(self):
        self.ensure_one()
        payload = self._graph_get(self.page_id, {"fields": "id,name"})
        page_forms = self._graph_get(self.page_id + "/leadgen_forms", {"fields": "id,name", "limit": 100})
        accessible_forms = {str(form.get("id")): form.get("name") for form in page_forms.get("data", [])}
        configured_forms = set(self.mapping_ids.filtered("active").mapped("facebook_form_id"))
        for form_id in configured_forms:
            self._graph_get(form_id + "/leads", {"fields": "id", "limit": 1})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Connection and Lead Access Successful"),
            "message": _("Page %(page)s; %(count)s accessible lead form(s).", page=payload.get("name") or payload.get("id"), count=len(accessible_forms)),
            "type": "success",
        }}

    def action_sync_backlog_now(self):
        self.ensure_one()
        self.full_sync_requested = True
        cron = self.env.ref("zencore_facebook_leads.ir_cron_facebook_backup_sync", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Facebook Backlog Sync Requested"),
            "message": _("The background worker will retrieve and queue accessible historical leads."),
            "type": "success",
        }}

    @api.model
    def _cron_backup_sync(self):
        now = fields.Datetime.now()
        for config in self.sudo().search([
            ("active", "=", True), "|", ("auto_sync", "=", True), ("full_sync_requested", "=", True)
        ]):
            interval = int(config.sync_interval or 15)
            if not config.full_sync_requested and config.last_sync_at and (now - config.last_sync_at).total_seconds() < interval * 60:
                continue
            try:
                config._backup_sync(full=config.full_sync_requested)
                config.write({"last_sync_at": now, "full_sync_requested": False})
            except Exception as exc:
                config._record_failure(exc)
                _logger.exception("Facebook backup sync failed for configuration %s", config.id)

    def _backup_sync(self, full=False):
        self.ensure_one()
        forms = {
            line.facebook_form_id: line.facebook_form_name
            for line in self.mapping_ids.filtered("active")
            if line.facebook_form_id
        }
        try:
            page_forms = self._graph_get(self.page_id + "/leadgen_forms", {"fields": "id,name", "limit": 100})
            forms.update({str(form["id"]): form.get("name") for form in page_forms.get("data", [])})
        except Exception:
            if not forms:
                raise
            _logger.warning(
                "Could not list forms for Facebook configuration %s; using configured form IDs.",
                self.id,
                exc_info=True,
            )

        imported = 0
        for form_id, form_name in forms.items():
            after = False
            while True:
                params = {
                    "fields": "id,created_time,field_data,form_id,ad_id,campaign_id,campaign_name",
                    "limit": 100,
                }
                if not full and self.last_sync_at:
                    sync_datetime = fields.Datetime.to_datetime(self.last_sync_at).replace(tzinfo=timezone.utc)
                    params["since"] = int(sync_datetime.timestamp())
                if after:
                    params["after"] = after
                payload = self._graph_get(str(form_id) + "/leads", params)
                for lead_data in payload.get("data", []):
                    lead_id = str(lead_data.get("id") or "")
                    if not lead_id or self.env["facebook.lead.log"].sudo().search_count([("facebook_lead_id", "=", lead_id)]):
                        continue
                    try:
                        with self.env.cr.savepoint():
                            self.env["facebook.lead.log"].sudo().create({
                                "config_id": self.id, "facebook_lead_id": lead_id,
                                "facebook_form_id": str(form_id), "facebook_form_name": form_name,
                                "raw_reference": lead_data, "status": "pending",
                            })
                            imported += 1
                    except IntegrityError:
                        continue
                paging = payload.get("paging") or {}
                after = (paging.get("cursors") or {}).get("after") if paging.get("next") else False
                if not after:
                    break
        return imported

    def _record_failure(self, exc):
        new_count = self.consecutive_failures + 1
        self.sudo().write({
            "last_error_at": fields.Datetime.now(), "last_error_message": str(exc)[:2000],
            "consecutive_failures": new_count,
        })
        if new_count == 3:
            user = self.default_user_id or self.env.ref("base.user_admin", raise_if_not_found=False)
            if user:
                self.sudo().activity_schedule(
                    "mail.mail_activity_data_todo", user_id=user.id,
                    summary=_("Facebook Lead Integration Requires Attention"),
                    note=str(exc)[:2000],
                )

    def _record_success(self):
        self.sudo().write({
            "last_success_at": fields.Datetime.now(), "last_error_message": False,
            "consecutive_failures": 0,
        })
