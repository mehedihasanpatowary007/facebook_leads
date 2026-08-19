from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    facebook_lead_id = fields.Char(copy=False, index=True, readonly=True)
    facebook_page_id = fields.Char(copy=False, index=True, readonly=True)
    facebook_form_id = fields.Char(copy=False, index=True, readonly=True)
    facebook_form_name = fields.Char(copy=False, readonly=True)
    facebook_ad_id = fields.Char(copy=False, readonly=True)
    facebook_campaign_id = fields.Char(copy=False, index=True, readonly=True)
    facebook_submission_date = fields.Datetime(copy=False, readonly=True)
    facebook_config_id = fields.Many2one(
        "facebook.lead.config", copy=False, readonly=True, ondelete="restrict"
    )

    _facebook_lead_id_unique = models.Constraint(
        "UNIQUE(facebook_lead_id)",
        "A CRM lead already exists for this Facebook Lead ID.",
    )
