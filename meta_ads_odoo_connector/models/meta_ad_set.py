# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MetaAdSet(models.Model):
    _name = 'meta.ad.set'
    _description = 'Meta Ad Set'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', required=True, ondelete='cascade', index=True)
    campaign_id = fields.Many2one('meta.campaign', ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='ad_account_id.currency_id', store=True, readonly=True)

    meta_adset_id = fields.Char(required=True, index=True)
    meta_campaign_id = fields.Char(index=True)
    status = fields.Char(index=True, tracking=True)
    effective_status = fields.Char(index=True)
    optimization_goal = fields.Char()
    billing_event = fields.Char()
    bid_strategy = fields.Char()
    daily_budget = fields.Monetary(currency_field='currency_id')
    lifetime_budget = fields.Monetary(currency_field='currency_id')
    start_time = fields.Datetime()
    end_time = fields.Datetime()
    targeting_json = fields.Json()
    promoted_object_json = fields.Json()
    attribution_spec_json = fields.Json()
    last_sync_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    ad_ids = fields.One2many('meta.ad', 'adset_id')
    ad_count = fields.Integer(compute='_compute_counts')

    # _sql_constraints = [
    #     ('meta_adset_company_unique', 'unique(company_id, meta_adset_id)', 'This Meta ad set already exists for this company.'),
    # ]

    @api.depends('ad_ids')
    def _compute_counts(self):
        for rec in self:
            rec.ad_count = len(rec.ad_ids)

    @api.model
    def _sync_from_account(self, account):
        fields_param = ','.join([
            'id', 'name', 'campaign_id', 'status', 'effective_status', 'optimization_goal',
            'billing_event', 'bid_strategy', 'daily_budget', 'lifetime_budget', 'start_time',
            'end_time', 'targeting', 'promoted_object', 'attribution_spec'
        ])
        for item in self._meta_graph_get_paged(account.config_id, '%s/adsets' % account._act_path(), params={
            'fields': fields_param,
            'limit': 100,
        }):
            self._upsert_from_meta(account, item)
        return True

    @api.model
    def _upsert_from_meta(self, account, item):
        meta_campaign_id = item.get('campaign_id')
        campaign = self.env['meta.campaign'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_campaign_id', '=', meta_campaign_id),
        ], limit=1)
        vals = {
            'name': item.get('name') or item.get('id'),
            'company_id': account.company_id.id,
            'config_id': account.config_id.id,
            'ad_account_id': account.id,
            'campaign_id': campaign.id or False,
            'meta_adset_id': item.get('id'),
            'meta_campaign_id': meta_campaign_id,
            'status': item.get('status'),
            'effective_status': item.get('effective_status'),
            'optimization_goal': item.get('optimization_goal'),
            'billing_event': item.get('billing_event'),
            'bid_strategy': item.get('bid_strategy'),
            'daily_budget': self._meta_amount_to_float(item.get('daily_budget')),
            'lifetime_budget': self._meta_amount_to_float(item.get('lifetime_budget')),
            'start_time': item.get('start_time'),
            'end_time': item.get('end_time'),
            'targeting_json': item.get('targeting'),
            'promoted_object_json': item.get('promoted_object'),
            'attribution_spec_json': item.get('attribution_spec'),
            'last_sync_at': fields.Datetime.now(),
            'raw_payload': item,
        }
        existing = self.search([('company_id', '=', account.company_id.id), ('meta_adset_id', '=', item.get('id'))], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
