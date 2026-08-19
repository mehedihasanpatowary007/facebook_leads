from odoo import fields, models


class FacebookCampaignMapping(models.Model):
    _name = "facebook.campaign.mapping"
    _description = "Facebook Campaign Mapping"
    _order = "config_id, facebook_campaign_name"

    config_id = fields.Many2one("facebook.lead.config", required=True, ondelete="cascade")
    facebook_campaign_id = fields.Char(index=True)
    facebook_campaign_name = fields.Char(required=True)
    campaign_id = fields.Many2one("utm.campaign", required=True, ondelete="restrict")
    active = fields.Boolean(default=True)

    _campaign_mapping_unique = models.Constraint(
        "UNIQUE(config_id, facebook_campaign_name)",
        "A Facebook campaign name can only be mapped once per configuration.",
    )
