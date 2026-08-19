from odoo import models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def _merge_opportunity(self, user_id=False, team_id=False, auto_unlink=True, max_length=0):
        # force unlimited merge
        return super()._merge_opportunity(
            user_id=user_id,
            team_id=team_id,
            auto_unlink=auto_unlink,
            max_length=False
        )