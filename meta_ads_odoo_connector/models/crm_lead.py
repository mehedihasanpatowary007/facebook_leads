# -*- coding: utf-8 -*-
from odoo import models, fields


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    x_meta_leadgen_id = fields.Char(string='Meta Leadgen ID', index=True, copy=False)
    x_meta_form_id = fields.Char(string='Meta Form ID', index=True, copy=False)
    x_meta_page_id = fields.Char(string='Meta Page ID', index=True, copy=False)
    x_meta_campaign_id = fields.Char(string='Meta Campaign ID', index=True, copy=False)
    x_meta_adset_id = fields.Char(string='Meta Ad Set ID', index=True, copy=False)
    x_meta_ad_id = fields.Char(string='Meta Ad ID', index=True, copy=False)
    x_meta_created_time = fields.Datetime(string='Meta Created Time', copy=False)
    x_meta_raw_payload = fields.Json(string='Meta Raw Payload', copy=False, groups='meta_ads_odoo_connector.group_meta_ads_technical')

    meta_campaign_ref_id = fields.Many2one('meta.campaign', string='Meta Campaign', compute='_compute_meta_refs', store=False)
    meta_adset_ref_id = fields.Many2one('meta.ad.set', string='Meta Ad Set', compute='_compute_meta_refs', store=False)
    meta_ad_ref_id = fields.Many2one('meta.ad', string='Meta Ad', compute='_compute_meta_refs', store=False)

    def _compute_meta_refs(self):
        Campaign = self.env['meta.campaign']
        AdSet = self.env['meta.ad.set']
        Ad = self.env['meta.ad']
        for lead in self:
            domain_company = [('company_id', '=', lead.company_id.id)] if lead.company_id else []
            lead.meta_campaign_ref_id = Campaign.search(domain_company + [('meta_campaign_id', '=', lead.x_meta_campaign_id)], limit=1) if lead.x_meta_campaign_id else False
            lead.meta_adset_ref_id = AdSet.search(domain_company + [('meta_adset_id', '=', lead.x_meta_adset_id)], limit=1) if lead.x_meta_adset_id else False
            lead.meta_ad_ref_id = Ad.search(domain_company + [('meta_ad_id', '=', lead.x_meta_ad_id)], limit=1) if lead.x_meta_ad_id else False
