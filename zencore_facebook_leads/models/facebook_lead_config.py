import logging
import secrets
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
    account_id = fields.Many2one("facebook.lead.account", ondelete="set null")
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
        default=lambda self: self.env["ir.config_parameter"].sudo().get_param("web.base.url").rstrip("/") + "/meta_lead_ads/webhook",
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
    form_ids = fields.One2many("facebook.lead.form", "config_id", string="Lead Forms")
    form_count = fields.Integer(compute="_compute_form_count")
    webhook_subscribed = fields.Boolean(readonly=True, copy=False)
    webhook_subscription_error = fields.Text(readonly=True, copy=False)

    _page_company_unique = models.Constraint(
        "UNIQUE(page_id, company_id)", "This Facebook Page is already configured for this company."
    )

    def _compute_form_count(self):
        for record in self:
            record.form_count = len(record.form_ids)

    @api.model_create_multi
    def create(self, vals_list):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url").rstrip("/")
        for values in vals_list:
            values.setdefault("verify_token", secrets.token_urlsafe(32))
            values.setdefault("webhook_url", base_url + "/meta_lead_ads/webhook")
        return super().create(vals_list)

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

    @api.constrains("api_version")
    def _check_api_version(self):
        for record in self:
            version = (record.api_version or "").strip()
            if not version.startswith("v") or not version[1:].replace(".", "", 1).isdigit():
                raise ValidationError(_("Graph API Version must use a value such as v25.0."))

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

    def _graph_iter(self, object_id, params=None):
        self.ensure_one()
        values = dict(params or {})
        after = False
        while True:
            if after:
                values["after"] = after
            payload = self._graph_get(object_id, values)
            yield from payload.get("data", [])
            paging = payload.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after") if paging.get("next") else False
            if not after:
                break

    def _graph_post(self, object_id, params=None):
        self.ensure_one()
        clean_version = self.api_version.strip().strip("/")
        url = urljoin("https://graph.facebook.com/%s/" % clean_version, str(object_id).strip("/"))
        safe_params = dict(params or {})
        safe_params["access_token"] = self.page_access_token
        try:
            response = requests.post(url, data=safe_params, timeout=30)
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(_("Meta API is unavailable: %s") % exc) from exc
        except ValueError as exc:
            raise UserError(_("Meta API returned an invalid response.")) from exc
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error") or {}
            raise UserError(_("Meta API error [code %(code)s]: %(message)s", code=error.get("code") or response.status_code, message=error.get("message") or response.reason))
        return payload

    def _subscribe_webhook(self):
        self.ensure_one()
        if not self.account_id:
            raise UserError(_("Connect this Page through a Facebook Connection before automatic webhook setup."))
        app_secret = self.account_id.app_secret or self.app_secret
        if not app_secret:
            raise UserError(_("The Meta App Secret is missing."))
        self.account_id._request("POST", self.app_id + "/subscriptions", {
            "object": "page",
            "callback_url": self.webhook_url,
            "verify_token": self.verify_token,
            "fields": "leadgen",
            "include_values": "true",
        }, token="%s|%s" % (self.app_id, app_secret))
        self._graph_post(self.page_id + "/subscribed_apps", {"subscribed_fields": "leadgen"})
        self.write({"webhook_subscribed": True, "webhook_subscription_error": False})
        return True

    def action_subscribe_webhook(self):
        self.ensure_one()
        try:
            self._subscribe_webhook()
            notification_type = "success"
            message = _("This Page now sends new lead notifications to the connected Meta App.")
        except UserError as exc:
            self.write({"webhook_subscribed": False, "webhook_subscription_error": str(exc)[:2000]})
            notification_type = "warning"
            message = str(exc)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Webhook Subscription"),
            "message": message,
            "type": notification_type,
            "sticky": notification_type == "warning",
        }}

    def action_import_forms(self):
        self.ensure_one()
        Form = self.env["facebook.lead.form"].sudo()
        imported = 0
        failures = 0
        for item in self._graph_iter(self.page_id + "/leadgen_forms", {"fields": "id,name,status", "limit": 100}):
            facebook_form_id = str(item.get("id") or "")
            if not facebook_form_id:
                continue
            form = Form.search([("config_id", "=", self.id), ("facebook_form_id", "=", facebook_form_id)], limit=1)
            values = {"name": item.get("name") or facebook_form_id, "status": item.get("status")}
            if form:
                form.write(values)
            else:
                values.update({"config_id": self.id, "facebook_form_id": facebook_form_id})
                form = Form.create(values)
            try:
                self._import_form_questions(form)
                form.write({"last_error_message": False, "last_refreshed_at": fields.Datetime.now()})
            except UserError as exc:
                form.write({"last_error_message": str(exc)[:2000]})
                failures += 1
            imported += 1
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Lead Forms Imported"),
            "message": _("%(count)s form(s) imported; %(failed)s field refresh(es) require attention.", count=imported, failed=failures),
            "type": "warning" if failures else "success",
        }}

    def _import_form_questions(self, form):
        self.ensure_one()
        payload = self._graph_get(form.facebook_form_id, {"fields": "id,name,status,questions"})
        questions = payload.get("questions") or []
        model = self.env["ir.model"]._get("crm.lead")
        target_names = {
            "full_name": "contact_name",
            "email": "email_from", "phone_number": "phone", "phone": "phone",
            "company_name": "partner_name", "job_title": "function", "city": "city",
            "state": "state_id", "zip_code": "zip", "country": "country_id",
        }
        target_fields = {
            field.name: field for field in self.env["ir.model.fields"].sudo().search([
                ("model_id", "=", model.id), ("name", "in", list(set(target_names.values())))
            ])
        }
        Mapping = self.env["facebook.lead.mapping"].sudo()
        for sequence, question in enumerate(questions, 1):
            key = question.get("key") or question.get("name")
            if not key:
                continue
            mapping = Mapping.search([("config_id", "=", self.id), ("facebook_form_id", "=", form.facebook_form_id), ("facebook_field_name", "=", key)], limit=1)
            values = {
                "form_id": form.id,
                "facebook_form_name": form.name,
                "sequence": sequence * 10,
            }
            target = target_fields.get(target_names.get(key))
            if target and not mapping:
                values["odoo_field_id"] = target.id
            if mapping:
                mapping.write(values)
            else:
                values.update({"config_id": self.id, "facebook_form_id": form.facebook_form_id, "facebook_field_name": key})
                Mapping.create(values)
        return True

    def action_open_forms(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Facebook Lead Forms"),
            "res_model": "facebook.lead.form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("config_id", "=", self.id)],
            "context": {"default_config_id": self.id},
        }

    def _sync_single_form(self, form, full=False):
        self.ensure_one()
        before = self.env["facebook.lead.log"].sudo().search_count([("config_id", "=", self.id)])
        self._backup_sync(full=full, selected_forms=form)
        after = self.env["facebook.lead.log"].sudo().search_count([("config_id", "=", self.id)])
        return after - before

    def action_test_connection(self):
        self.ensure_one()
        payload = self._graph_get(self.page_id, {"fields": "id,name"})
        configured_forms = set(self.mapping_ids.filtered("active").mapped("facebook_form_id"))
        if configured_forms:
            for form_id in configured_forms:
                self._graph_get(form_id + "/leads", {"fields": "id", "limit": 1})
            form_count = len(configured_forms)
        else:
            page_forms = self._graph_get(self.page_id + "/leadgen_forms", {"fields": "id,name", "limit": 100})
            form_count = len(page_forms.get("data", []))
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Connection and Lead Access Successful"),
            "message": _("Page %(page)s; %(count)s configured lead form(s) verified.", page=payload.get("name") or payload.get("id"), count=form_count),
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

    def _backup_sync(self, full=False, selected_forms=None):
        self.ensure_one()
        selected_forms = selected_forms if selected_forms is not None else self.form_ids
        forms = {
            form.facebook_form_id: form.name
            for form in selected_forms.filtered("active")
            if form.facebook_form_id
        }
        if selected_forms is None or selected_forms == self.form_ids:
            forms.update({
                line.facebook_form_id: line.facebook_form_name
                for line in self.mapping_ids.filtered("active")
                if line.facebook_form_id
            })
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
