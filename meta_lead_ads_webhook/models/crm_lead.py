# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    meta_leadgen_id = fields.Char(string='Meta LeadGen ID', index=True, copy=False, readonly=True)
    meta_form_id = fields.Char(string='Meta Form ID', index=True, copy=False, readonly=True)
    meta_page_id = fields.Char(string='Meta Page ID', index=True, copy=False, readonly=True)
    meta_ad_id = fields.Char(string='Meta Ad ID', index=True, copy=False, readonly=True)
    meta_ad_name = fields.Char(string='Meta Ad Name', copy=False, readonly=True)
    meta_adset_id = fields.Char(string='Meta Ad Set ID', index=True, copy=False, readonly=True)
    meta_adset_name = fields.Char(string='Meta Ad Set Name', copy=False, readonly=True)
    meta_campaign_id = fields.Char(string='Meta Campaign ID', index=True, copy=False, readonly=True)
    meta_campaign_name = fields.Char(string='Meta Campaign Name', copy=False, readonly=True)
    meta_platform = fields.Char(string='Meta Platform', copy=False, readonly=True)
    meta_is_organic = fields.Boolean(string='Meta Organic Lead', copy=False, readonly=True)
    meta_created_time = fields.Datetime(string='Meta Created Time', copy=False, readonly=True)
    meta_raw_payload = fields.Json(string='Meta Raw Payload', copy=False, readonly=True)
    meta_queue_id = fields.Many2one('meta.lead.queue', string='Meta Queue Record', copy=False, readonly=True)

    # _sql_constraints = [
    #     ('meta_leadgen_id_unique', 'unique(meta_leadgen_id)', 'This Meta lead has already been imported into CRM.'),
    # ]
