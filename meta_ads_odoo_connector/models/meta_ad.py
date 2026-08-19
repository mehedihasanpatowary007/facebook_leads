# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MetaAd(models.Model):
    _name = 'meta.ad'
    _description = 'Meta Ad'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', required=True, ondelete='cascade', index=True)
    campaign_id = fields.Many2one('meta.campaign', ondelete='cascade', index=True)
    adset_id = fields.Many2one('meta.ad.set', ondelete='cascade', index=True)
    creative_id = fields.Many2one('meta.ad.creative', ondelete='set null', index=True)

    meta_ad_id = fields.Char(required=True, index=True)
    meta_campaign_id = fields.Char(index=True)
    meta_adset_id = fields.Char(index=True)
    meta_creative_id = fields.Char(index=True)
    status = fields.Char(index=True, tracking=True)
    effective_status = fields.Char(index=True)
    preview_shareable_link = fields.Char()
    tracking_specs_json = fields.Json()
    conversion_domain = fields.Char()
    last_sync_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    # _sql_constraints = [
    #     ('meta_ad_company_unique', 'unique(company_id, meta_ad_id)', 'This Meta ad already exists for this company.'),
    # ]

    @api.model
    def _sync_from_account(self, account):
        fields_param = ','.join([
            'id', 'name', 'campaign_id', 'adset_id', 'creative{id,name,object_story_id,object_story_spec,title,body,image_hash,image_url,thumbnail_url,url_tags,asset_feed_spec}',
            'status', 'effective_status', 'preview_shareable_link', 'tracking_specs', 'conversion_domain'
        ])
        for item in self._meta_graph_get_paged(account.config_id, '%s/ads' % account._act_path(), params={
            'fields': fields_param,
            'limit': 100,
        }):
            self._upsert_from_meta(account, item)
        return True

    @api.model
    def _upsert_from_meta(self, account, item):
        campaign = self.env['meta.campaign'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_campaign_id', '=', item.get('campaign_id')),
        ], limit=1)
        adset = self.env['meta.ad.set'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_adset_id', '=', item.get('adset_id')),
        ], limit=1)
        creative = False
        creative_data = item.get('creative') or {}
        if creative_data and creative_data.get('id'):
            creative = self.env['meta.ad.creative']._upsert_from_meta(account, creative_data)
        vals = {
            'name': item.get('name') or item.get('id'),
            'company_id': account.company_id.id,
            'config_id': account.config_id.id,
            'ad_account_id': account.id,
            'campaign_id': campaign.id or False,
            'adset_id': adset.id or False,
            'creative_id': creative.id if creative else False,
            'meta_ad_id': item.get('id'),
            'meta_campaign_id': item.get('campaign_id'),
            'meta_adset_id': item.get('adset_id'),
            'meta_creative_id': creative_data.get('id'),
            'status': item.get('status'),
            'effective_status': item.get('effective_status'),
            'preview_shareable_link': item.get('preview_shareable_link'),
            'tracking_specs_json': item.get('tracking_specs'),
            'conversion_domain': item.get('conversion_domain'),
            'last_sync_at': fields.Datetime.now(),
            'raw_payload': item,
        }
        existing = self.search([('company_id', '=', account.company_id.id), ('meta_ad_id', '=', item.get('id'))], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
