import secrets
import logging
from datetime import timedelta
from urllib.parse import urlencode, urljoin

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FacebookLeadAccount(models.Model):
    _name = "facebook.lead.account"
    _description = "Facebook Lead Account"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "company_id, name"

    name = fields.Char(required=True, default="Facebook Lead Ads")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    app_id = fields.Char(string="Meta App ID", required=True, tracking=True)
    app_secret = fields.Char(required=True, groups="sales_team.group_sale_manager", copy=False)
    api_version = fields.Char(string="Graph API Version", default="v25.0", required=True)
    verify_token = fields.Char(required=True, default=lambda self: secrets.token_urlsafe(32), groups="sales_team.group_sale_manager", copy=False)
    user_access_token = fields.Char(groups="sales_team.group_sale_manager", copy=False)
    token_expires_at = fields.Datetime(readonly=True, copy=False)
    oauth_redirect_uri = fields.Char(compute="_compute_oauth_redirect_uri", string="OAuth Redirect URL")
    oauth_state = fields.Char(readonly=True, copy=False, groups="sales_team.group_sale_manager")
    oauth_state_expires_at = fields.Datetime(readonly=True, copy=False)
    oauth_user_id = fields.Many2one("res.users", readonly=True, copy=False)
    connected = fields.Boolean(compute="_compute_connected")
    page_ids = fields.One2many("facebook.lead.config", "account_id", string="Facebook Pages")
    page_count = fields.Integer(compute="_compute_page_count")

    _app_company_unique = models.Constraint(
        "UNIQUE(app_id, company_id)", "This Meta App is already configured for this company."
    )

    @api.constrains("api_version")
    def _check_api_version(self):
        for record in self:
            version = (record.api_version or "").strip()
            if not version.startswith("v") or not version[1:].replace(".", "", 1).isdigit():
                raise ValidationError(_("Graph API Version must use a value such as v25.0."))

    def _compute_connected(self):
        for record in self:
            record.connected = bool(record.user_access_token)

    def _compute_page_count(self):
        for record in self:
            record.page_count = len(record.page_ids)

    def _compute_oauth_redirect_uri(self):
        for record in self:
            record.oauth_redirect_uri = record._redirect_uri()

    def _base_url(self):
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url").rstrip("/")

    def _redirect_uri(self):
        return self._base_url() + "/facebook_leads/oauth/callback"

    def _graph_url(self, endpoint):
        version = self.api_version.strip().strip("/")
        return urljoin("https://graph.facebook.com/%s/" % version, str(endpoint).strip("/"))

    def _request(self, method, endpoint, params=None, token=None):
        self.ensure_one()
        values = dict(params or {})
        access_token = self.user_access_token if token is None else token
        if access_token:
            values["access_token"] = access_token
        try:
            response = requests.request(method, self._graph_url(endpoint), params=values, timeout=30)
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(_("Meta API is unavailable: %s") % exc) from exc
        except ValueError as exc:
            raise UserError(_("Meta API returned an invalid response.")) from exc
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error") or {}
            raise UserError(_("Meta API error [code %(code)s]: %(message)s", code=error.get("code") or response.status_code, message=error.get("message") or response.reason))
        return payload

    def _iter_graph_data(self, endpoint, params=None, token=None):
        self.ensure_one()
        values = dict(params or {})
        after = False
        while True:
            if after:
                values["after"] = after
            payload = self._request("GET", endpoint, values, token=token)
            yield from payload.get("data", [])
            paging = payload.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after") if paging.get("next") else False
            if not after:
                break

    def action_connect_facebook(self):
        self.ensure_one()
        if not self.app_id or not self.app_secret:
            raise ValidationError(_("Enter the Meta App ID and App Secret before connecting."))
        state = secrets.token_urlsafe(32)
        self.write({
            "oauth_state": state,
            "oauth_state_expires_at": fields.Datetime.now() + timedelta(minutes=15),
            "oauth_user_id": self.env.user.id,
        })
        query = urlencode({
            "client_id": self.app_id,
            "redirect_uri": self._redirect_uri(),
            "state": state,
            "response_type": "code",
            "scope": ",".join(("leads_retrieval", "pages_show_list", "pages_read_engagement", "pages_manage_metadata", "pages_manage_ads")),
        })
        return {"type": "ir.actions.act_url", "url": "https://www.facebook.com/%s/dialog/oauth?%s" % (self.api_version.strip("/"), query), "target": "self"}

    def _exchange_code(self, code):
        self.ensure_one()
        payload = self._request("GET", "oauth/access_token", {
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "redirect_uri": self._redirect_uri(),
            "code": code,
        }, token=False)
        token = payload.get("access_token")
        if not token:
            raise UserError(_("Meta did not return an access token."))
        expires = payload.get("expires_in")
        try:
            long_lived = self._request("GET", "oauth/access_token", {
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": token,
            }, token=False)
            token = long_lived.get("access_token") or token
            expires = long_lived.get("expires_in") or expires
        except UserError:
            # Some development/test tokens cannot be exchanged. The valid short-lived
            # token remains usable and its expiry is shown to the administrator.
            _logger.info("Meta short-lived token could not be exchanged for a long-lived token", exc_info=True)
        self.write({
            "user_access_token": token,
            "token_expires_at": fields.Datetime.now() + timedelta(seconds=int(expires)) if expires else False,
            "oauth_state": False,
            "oauth_state_expires_at": False,
            "oauth_user_id": False,
        })
        return self.action_import_pages()

    def action_import_pages(self):
        self.ensure_one()
        if not self.user_access_token:
            raise UserError(_("Connect Facebook before importing Pages."))
        Config = self.env["facebook.lead.config"].sudo()
        imported = 0
        subscribed = 0
        subscription_failures = 0
        for page in self._iter_graph_data("me/accounts", {"fields": "id,name,access_token,tasks", "limit": 100}):
            page_id = str(page.get("id") or "")
            page_token = page.get("access_token")
            if not page_id or not page_token:
                continue
            config = Config.search([("page_id", "=", page_id), ("company_id", "=", self.company_id.id)], limit=1)
            values = {
                "name": page.get("name") or page_id,
                "page_name": page.get("name"),
                "page_id": page_id,
                "page_access_token": page_token,
                "account_id": self.id,
                "app_id": self.app_id,
                "app_secret": self.app_secret,
                "api_version": self.api_version,
                "company_id": self.company_id.id,
                "verify_token": self.verify_token,
                "webhook_url": self._base_url() + "/meta_lead_ads/webhook",
            }
            if config:
                config.write(values)
            else:
                config = Config.create(values)
            imported += 1
            try:
                config._subscribe_webhook()
                subscribed += 1
            except UserError as exc:
                config.sudo().write({"webhook_subscribed": False, "webhook_subscription_error": str(exc)[:2000]})
                subscription_failures += 1
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Facebook Pages Imported"),
            "message": _("%(count)s Page(s) imported; %(subscribed)s webhook subscription(s) active; %(failed)s require attention.", count=imported, subscribed=subscribed, failed=subscription_failures),
            "type": "warning" if subscription_failures else "success",
            "next": {
                "type": "ir.actions.act_window",
                "name": _("Facebook Pages"),
                "res_model": "facebook.lead.config",
                "views": [(False, "list"), (False, "form")],
                "domain": [("account_id", "=", self.id)],
                "context": {"default_account_id": self.id},
            },
        }}

    def action_open_pages(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Facebook Pages"),
            "res_model": "facebook.lead.config",
            "views": [(False, "list"), (False, "form")],
            "domain": [("account_id", "=", self.id)],
            "context": {"default_account_id": self.id},
        }

    def action_test_connection(self):
        self.ensure_one()
        profile = self._request("GET", "me", {"fields": "id,name"})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Facebook Connection Successful"),
            "message": _("Connected as %(name)s.", name=profile.get("name") or profile.get("id")),
            "type": "success",
        }}

    def action_disconnect(self):
        self.ensure_one()
        self.write({
            "user_access_token": False,
            "token_expires_at": False,
            "oauth_state": False,
            "oauth_state_expires_at": False,
            "oauth_user_id": False,
        })
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Facebook Disconnected"),
            "message": _("The user token was removed from Odoo. Existing Page tokens were not revoked at Meta."),
            "type": "warning",
        }}
