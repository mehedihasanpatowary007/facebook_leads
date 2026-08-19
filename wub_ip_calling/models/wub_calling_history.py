from odoo import fields, models


class WubCallingHistory(models.Model):
    _name = "wub.calling.history"
    _description = "Calling History"
    _order = "id desc"

    lead_id = fields.Many2one(
        "crm.lead",
        required=True,
        ondelete="cascade",
    )

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="restrict",
    )

    phone_number = fields.Char(
        required=True,
    )

    request_time = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
    )

    call_time = fields.Datetime()

    status = fields.Char()
    call_status = fields.Char()

    agent_id = fields.Char()
    agent_full_name = fields.Char()

    campaign = fields.Char()

    length_in_sec = fields.Integer()

    term_reason = fields.Char()

    recording_url = fields.Char()

    queue_seconds = fields.Integer()

    request_payload = fields.Text()

    response_payload = fields.Text()