from odoo import fields, models


class WubCallLog(models.Model):
    _name = "wub.call.log"
    _description = "IP Call Log"
    _order = "call_start_time desc"

    call_id = fields.Char(
        required=True,
        index=True,
    )

    lead_id = fields.Many2one(
        "crm.lead",
        required=True,
        ondelete="cascade",
    )

    direction = fields.Selection(
        [
            ("incoming", "Incoming"),
            ("outgoing", "Outgoing"),
        ],
        required=True,
    )

    caller_user = fields.Char()
    caller_extension = fields.Char()

    customer_number = fields.Char()

    call_start_time = fields.Datetime()
    call_answer_time = fields.Datetime()
    call_end_time = fields.Datetime()

    ring_duration = fields.Integer()
    talk_duration = fields.Integer()
    total_duration = fields.Integer()

    call_status = fields.Selection(
        [
            ("answered", "Answered"),
            ("no_answer", "No Answer"),
            ("busy", "Busy"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ]
    )

    recording_url = fields.Char()

    remarks = fields.Text()

    _check_unique_call_id = models.Constraint(
        "UNIQUE(call_id)",
        "Call ID must be unique.",
    )