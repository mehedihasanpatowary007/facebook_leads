# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MetaAdCreative(models.Model):
    _name = 'meta.ad.creative'
    _description = 'Meta Ad Creative'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', required=True, ondelete='cascade', index=True)

    meta_creative_id = fields.Char(required=True, index=True)
    object_story_id = fields.Char(index=True)
    page_id = fields.Char(index=True)
    instagram_actor_id = fields.Char(index=True)
    title = fields.Char()
    body = fields.Text()
    call_to_action_type = fields.Char()
    image_hash = fields.Char(index=True)
    image_url = fields.Char()
    video_id = fields.Char(index=True)
    link_url = fields.Char()
    url_tags = fields.Char()
    asset_feed_spec_json = fields.Json()
    object_story_spec_json = fields.Json()
    thumbnail_url = fields.Char()
    last_sync_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    # _sql_constraints = [
    #     ('meta_creative_company_unique', 'unique(company_id, meta_creative_id)', 'This Meta creative already exists for this company.'),
    # ]

    @api.model
    def _upsert_from_meta(self, account, item):
        object_story_spec = item.get('object_story_spec') or {}
        link_data = object_story_spec.get('link_data') or {}
        video_data = object_story_spec.get('video_data') or {}
        call_to_action = link_data.get('call_to_action') or video_data.get('call_to_action') or {}
        vals = {
            'name': item.get('name') or item.get('id'),
            'company_id': account.company_id.id,
            'config_id': account.config_id.id,
            'ad_account_id': account.id,
            'meta_creative_id': item.get('id'),
            'object_story_id': item.get('object_story_id'),
            'page_id': object_story_spec.get('page_id'),
            'instagram_actor_id': object_story_spec.get('instagram_actor_id'),
            'title': item.get('title') or link_data.get('name') or video_data.get('title'),
            'body': item.get('body') or link_data.get('message') or video_data.get('message'),
            'call_to_action_type': call_to_action.get('type'),
            'image_hash': item.get('image_hash') or link_data.get('image_hash'),
            'image_url': item.get('image_url') or link_data.get('picture'),
            'video_id': video_data.get('video_id'),
            'link_url': link_data.get('link') or video_data.get('link'),
            'url_tags': item.get('url_tags'),
            'asset_feed_spec_json': item.get('asset_feed_spec'),
            'object_story_spec_json': object_story_spec,
            'thumbnail_url': item.get('thumbnail_url'),
            'last_sync_at': fields.Datetime.now(),
            'raw_payload': item,
        }
        existing = self.search([('company_id', '=', account.company_id.id), ('meta_creative_id', '=', item.get('id'))], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
