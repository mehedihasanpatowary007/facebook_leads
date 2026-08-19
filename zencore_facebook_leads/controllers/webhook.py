import hashlib
import hmac
import json
import logging

from psycopg2 import IntegrityError

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FacebookLeadWebhook(http.Controller):

    @http.route("/meta_lead_ads/webhook", type="http", auth="public", methods=["GET"], csrf=False)
    def verify(self, **params):
        token = params.get("hub.verify_token")
        config = request.env["facebook.lead.config"].sudo().search([
            ("active", "=", True), ("verify_token", "=", token)
        ], limit=1)
        if params.get("hub.mode") == "subscribe" and config and params.get("hub.challenge"):
            return request.make_response(params["hub.challenge"], headers=[("Content-Type", "text/plain")])
        return request.make_response("Forbidden", status=403)

    @http.route("/meta_lead_ads/webhook", type="http", auth="public", methods=["POST"], csrf=False)
    def receive(self, **params):
        raw = request.httprequest.get_data() or b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)
        queued = 0
        for entry in payload.get("entry", []):
            page_id = str(entry.get("id") or "")
            config = request.env["facebook.lead.config"].sudo().search([
                ("active", "=", True), ("page_id", "=", page_id)
            ], limit=1)
            if not config:
                continue
            if not self._valid_signature(config, raw):
                return request.make_json_response({"success": False, "error": "invalid_signature"}, status=403)
            for change in entry.get("changes", []):
                if change.get("field") != "leadgen":
                    continue
                value = change.get("value") or {}
                lead_id = str(value.get("leadgen_id") or "")
                if not lead_id:
                    continue
                try:
                    with request.env.cr.savepoint():
                        log = request.env["facebook.lead.log"].sudo().create({
                            "config_id": config.id, "facebook_lead_id": lead_id,
                            "facebook_form_id": str(value.get("form_id") or ""),
                            "raw_reference": value, "status": "pending",
                        })
                        queued += 1
                except IntegrityError:
                    log = request.env["facebook.lead.log"].sudo().search([("facebook_lead_id", "=", lead_id)], limit=1)
                if log and log.status in ("pending", "failed"):
                    log._process()
        return request.make_json_response({"success": True, "received": queued})

    @staticmethod
    def _valid_signature(config, raw):
        if not config.validate_signature:
            return True
        supplied = request.httprequest.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(config.app_secret.encode(), raw, hashlib.sha256).hexdigest()
        return bool(supplied) and hmac.compare_digest(supplied, expected)
