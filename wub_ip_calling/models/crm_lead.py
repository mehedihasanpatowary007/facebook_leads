from odoo import fields, models, _
from odoo.exceptions import UserError
import json
import requests
import urllib3

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

class CrmLead(models.Model):
    _inherit = "crm.lead"

    call_log_ids = fields.One2many(
        "wub.call.log",
        "lead_id",
        string="Call Logs",
    )

    call_log_count = fields.Integer(
        compute="_compute_call_log_count",
    )

    def _compute_call_log_count(self):
        for lead in self:
            lead.call_log_count = len(
                lead.call_log_ids
            )

    def action_ip_call(self):
        self.ensure_one()

        phone_number = self.phone or self.mobile

        if not phone_number:
            raise UserError(_("Please set a phone number first."))

        if not self.env.user.ip_calling_email:
            raise UserError(
                _("Please configure IP Calling Email on your user profile.")
            )

        history = self.env["wub.calling.history"].create({
            "lead_id": self.id,
            "user_id": self.env.user.id,
            "phone_number": phone_number,
        })

        payload = {
            "agent_email": self.env.user.ip_calling_email,
            "value": phone_number,
            "calling_history_id": history.id,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": "iHelpBD@Authorization@",
        }

        # Store request payload immediately
        history.write({
            "request_payload": json.dumps(payload, indent=4),
        })

        try:
            response = requests.post(
                "https://worlduni.ihelpbd.com/wub/api/click_to_call.php",
                headers=headers,
                json=payload,
                timeout=30,
                verify=False,
            )

            try:
                response_data = response.json()
            except ValueError:
                response_data = {
                    "status": "ERROR",
                    "data": {
                        "result_reason": response.text,
                    }
                }

        except Exception as e:
            history.write({
                "response_payload": str(e),
            })

            raise UserError(
                _("IP Calling Server Error:\n%s") % str(e)
            )

        history.write({
            "response_payload": json.dumps(
                response_data,
                indent=4,
                ensure_ascii=False,
            ),
        })

        message = response_data.get("data", {}).get(
            "result_reason",
            "Request processed."
        )

        notification_type = (
            "success"
            if response_data.get("status") == "SUCCESS"
            else "warning"
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("IP Calling"),
                "message": message,
                "sticky": False,
                "type": notification_type,
            },
        }
