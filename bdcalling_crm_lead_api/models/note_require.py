from odoo import models
from odoo.exceptions import UserError

class CrmLeadLost(models.TransientModel):
    _inherit = 'crm.lead.lost'

    def action_lost_reason_apply(self):
        if not self.lost_reason_id and not self.lost_feedback:
            raise UserError(
                "Please enter a Closing Note or select a Lost Reason before marking as lost."
            )
        return super().action_lost_reason_apply()