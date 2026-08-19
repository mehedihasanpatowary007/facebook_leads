import logging
from datetime import datetime, timedelta, timezone

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class FacebookLeadLog(models.Model):
    _name = "facebook.lead.log"
    _description = "Facebook Lead Integration Log"
    _order = "create_date desc, id desc"

    config_id = fields.Many2one("facebook.lead.config", required=True, ondelete="restrict", index=True)
    facebook_lead_id = fields.Char(required=True, index=True)
    facebook_form_id = fields.Char(index=True)
    facebook_form_name = fields.Char()
    student_name = fields.Char()
    status = fields.Selection([
        ("pending", "Pending"), ("processing", "Processing"), ("retry", "Retry"),
        ("success", "Success"), ("duplicate", "Duplicate"), ("failed", "Failed"),
    ], default="pending", required=True, index=True)
    crm_lead_id = fields.Many2one("crm.lead", readonly=True, ondelete="set null")
    error_message = fields.Text(readonly=True)
    retry_count = fields.Integer(readonly=True)
    next_retry_at = fields.Datetime(readonly=True, index=True)
    processing_started_at = fields.Datetime(readonly=True, index=True)
    raw_reference = fields.Json(copy=False)
    processed_at = fields.Datetime(readonly=True)

    _lead_log_unique = models.Constraint(
        "UNIQUE(facebook_lead_id)", "A log already exists for this Facebook Lead ID."
    )

    def action_retry(self):
        failed = self.env["facebook.lead.log"]
        for record in self:
            if record.status not in ("failed", "pending", "retry"):
                raise UserError(_("Only pending, retry, or failed leads can be retried."))
            record.write({"status": "pending", "error_message": False, "next_retry_at": False})
            if not record._process():
                failed |= record
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Facebook Lead Retry"),
            "message": _("Retry finished. %s record(s) still require attention.") % len(failed),
            "type": "warning" if failed else "success", "sticky": bool(failed),
        }}

    @api.model
    def _cron_process_pending(self):
        configs = self.env["facebook.lead.config"].sudo().search([("active", "=", True)])
        for config in configs:
            self._process_pending(config=config, limit=config.processing_batch_size)

    @api.model
    def _process_pending(self, config=None, limit=50):
        stale_before = fields.Datetime.now() - timedelta(minutes=15)
        stale_domain = [("status", "=", "processing"), ("processing_started_at", "<", stale_before)]
        if config:
            stale_domain.append(("config_id", "=", config.id))
        self.sudo().search(stale_domain).write({"status": "retry", "next_retry_at": fields.Datetime.now()})
        domain = [
            ("status", "in", ("pending", "retry")),
            "|", ("next_retry_at", "=", False), ("next_retry_at", "<=", fields.Datetime.now()),
        ]
        if config:
            domain.append(("config_id", "=", config.id))
        candidates = self.sudo().search(domain, order="create_date, id", limit=limit)
        processed = 0
        for candidate in candidates:
            self.env.cr.execute("SELECT id FROM facebook_lead_log WHERE id = %s FOR UPDATE SKIP LOCKED", [candidate.id])
            if not self.env.cr.fetchone():
                continue
            candidate.invalidate_recordset()
            if candidate.status not in ("pending", "retry"):
                continue
            candidate._process()
            processed += 1
        return processed

    @api.model
    def _cron_cleanup_logs(self):
        for config in self.env["facebook.lead.config"].sudo().search([]):
            cutoff = fields.Datetime.now() - timedelta(days=config.log_retention_days)
            self.sudo().search([
                ("config_id", "=", config.id), ("status", "in", ("success", "duplicate")),
                ("create_date", "<", cutoff),
            ]).unlink()

    def _process(self, lead_data=None):
        self.ensure_one()
        self.write({"status": "processing", "next_retry_at": False, "processing_started_at": fields.Datetime.now()})
        try:
            existing = self.env["crm.lead"].sudo().search([("facebook_lead_id", "=", self.facebook_lead_id)], limit=1)
            if existing:
                self.write({"status": "duplicate", "crm_lead_id": existing.id, "processed_at": fields.Datetime.now(), "processing_started_at": False, "error_message": _("Already processed")})
                return existing
            payload = lead_data or self.config_id._graph_get(self.facebook_lead_id, {"fields": "id,created_time,field_data,form_id,ad_id,campaign_id,campaign_name"})
            values = self._prepare_lead_values(payload)
            try:
                with self.env.cr.savepoint():
                    lead = self.env["crm.lead"].sudo().with_company(self.config_id.company_id).create(values)
            except IntegrityError:
                lead = self.env["crm.lead"].sudo().search([("facebook_lead_id", "=", self.facebook_lead_id)], limit=1)
                if not lead:
                    raise
                self.write({"status": "duplicate", "crm_lead_id": lead.id, "processed_at": fields.Datetime.now(), "processing_started_at": False, "error_message": _("Already processed concurrently")})
                return lead
            self.write({"status": "success", "crm_lead_id": lead.id, "student_name": lead.contact_name, "processed_at": fields.Datetime.now(), "processing_started_at": False, "error_message": False, "raw_reference": payload})
            self.config_id._record_success()
            return lead
        except Exception as exc:
            retry_count = self.retry_count + 1
            final = retry_count >= self.config_id.max_retry_count
            delay = self.config_id.retry_delay_minutes * (2 ** min(retry_count - 1, 6))
            self.write({
                "status": "failed" if final else "retry", "retry_count": retry_count,
                "next_retry_at": False if final else fields.Datetime.now() + timedelta(minutes=delay),
                "processing_started_at": False, "error_message": str(exc)[:4000], "processed_at": fields.Datetime.now(),
            })
            self.config_id._record_failure(exc)
            _logger.exception("Facebook lead processing failed for %s", self.facebook_lead_id)
            return False

    def _prepare_lead_values(self, payload):
        answers = self._answers_to_dict(payload.get("field_data") or [])
        form_id = str(payload.get("form_id") or self.facebook_form_id or "")
        mappings = self.env["facebook.lead.mapping"].sudo().search([
            ("config_id", "=", self.config_id.id), ("facebook_form_id", "=", form_id), ("active", "=", True)
        ])
        missing = mappings.filtered(lambda line: line.required and not answers.get(line.facebook_field_name))
        if missing:
            raise UserError(_("Required Facebook fields are missing: %s") % ", ".join(missing.mapped("facebook_field_name")))
        Lead = self.env["crm.lead"]
        values = {}
        for mapping in mappings:
            if not mapping.odoo_field_id:
                continue
            raw_value = answers.get(mapping.facebook_field_name)
            if raw_value not in (False, None, ""):
                values[mapping.odoo_field_id.name] = self._convert_value(Lead._fields[mapping.odoo_field_id.name], raw_value)
        split_name = " ".join(filter(None, (answers.get("first_name"), answers.get("last_name"))))
        name = values.get("contact_name") or answers.get("full_name") or answers.get("name") or split_name
        course = answers.get("interested_course") or answers.get("course") or values.get("course_id")
        values.setdefault("contact_name", name)
        values.setdefault("phone", answers.get("phone_number") or answers.get("phone"))
        values.setdefault("email_from", answers.get("email") or answers.get("email_address"))
        values["name"] = ("%s - %s" % (course, name)) if course and name else (("Facebook Lead - %s" % name) if name else "Facebook Lead - %s" % self.facebook_lead_id)
        values.update({
            "type": "lead", "company_id": self.config_id.company_id.id,
            "facebook_lead_id": self.facebook_lead_id, "facebook_page_id": self.config_id.page_id,
            "facebook_form_id": form_id, "facebook_form_name": self.facebook_form_name,
            "facebook_ad_id": payload.get("ad_id"), "facebook_campaign_id": payload.get("campaign_id"),
            "facebook_submission_date": self._parse_datetime(payload.get("created_time")), "facebook_config_id": self.config_id.id,
            "team_id": self.config_id.default_team_id.id or False, "user_id": self.config_id.default_user_id.id or False,
            "source_id": self.config_id.default_source_id.id or False, "medium_id": self.config_id.default_medium_id.id or False,
        })
        campaign = self.env["facebook.campaign.mapping"]
        campaign_id = str(payload.get("campaign_id") or "")
        campaign_name = payload.get("campaign_name") or ""
        if campaign_id or campaign_name:
            criteria = [("config_id", "=", self.config_id.id), ("active", "=", True)]
            if campaign_id and campaign_name:
                criteria += ["|", ("facebook_campaign_id", "=", campaign_id), ("facebook_campaign_name", "=", campaign_name)]
            elif campaign_id:
                criteria.append(("facebook_campaign_id", "=", campaign_id))
            else:
                criteria.append(("facebook_campaign_name", "=", campaign_name))
            campaign = campaign.sudo().search(criteria, limit=1)
        if campaign:
            values["campaign_id"] = campaign.campaign_id.id
        values = {key: value for key, value in values.items() if value not in (None, "")}
        return values

    @staticmethod
    def _answers_to_dict(field_data):
        result = {}
        for item in field_data:
            raw = item.get("values") or []
            result[item.get("name")] = raw[0] if len(raw) == 1 else ", ".join(map(str, raw))
        return result

    def _convert_value(self, field, value):
        if field.type in ("char", "text", "html", "selection"):
            return str(value)
        if field.type == "integer":
            return int(value)
        if field.type in ("float", "monetary"):
            return float(value)
        if field.type == "boolean":
            return str(value).lower() in ("1", "true", "yes", "y")
        if field.type == "many2one":
            match = self.env[field.comodel_name].sudo().search([("name", "=ilike", str(value))], limit=1)
            if not match:
                raise UserError(_("No %s record matches '%s'.") % (field.comodel_name, value))
            return match.id
        if field.type in ("many2many", "one2many"):
            raise UserError(_("Relational list field %s is not supported by direct mapping.") % field.name)
        return value

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
        except (TypeError, ValueError):
            return False
