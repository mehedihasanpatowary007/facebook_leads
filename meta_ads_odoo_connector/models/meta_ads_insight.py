# -*- coding: utf-8 -*-
import json

from odoo import models, fields, api


class MetaAdsInsight(models.Model):
    _name = 'meta.ads.insight'
    _description = 'Meta Ads Insight'
    _inherit = ['meta.api.mixin']
    _order = 'date_start desc, spend desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='ad_account_id.currency_id', store=True, readonly=True)

    date_start = fields.Date(required=True, index=True)
    date_stop = fields.Date(required=True, index=True)

    campaign_id = fields.Many2one('meta.campaign', ondelete='set null', index=True)
    adset_id = fields.Many2one('meta.ad.set', ondelete='set null', index=True)
    ad_id = fields.Many2one('meta.ad', ondelete='set null', index=True)

    meta_campaign_id = fields.Char(index=True)
    meta_adset_id = fields.Char(index=True)
    meta_ad_id = fields.Char(index=True)
    campaign_name = fields.Char()
    adset_name = fields.Char()
    ad_name = fields.Char()

    impressions = fields.Integer()
    reach = fields.Integer()
    frequency = fields.Float()
    spend = fields.Monetary(currency_field='currency_id')
    clicks = fields.Integer()
    inline_link_clicks = fields.Integer()
    ctr = fields.Float(string='CTR')
    cpc = fields.Monetary(string='CPC', currency_field='currency_id')
    cpm = fields.Monetary(string='CPM', currency_field='currency_id')
    cpp = fields.Monetary(string='CPP', currency_field='currency_id')

    leads = fields.Integer()
    purchases = fields.Integer()
    purchase_value = fields.Monetary(currency_field='currency_id')
    cost_per_lead = fields.Monetary(currency_field='currency_id', compute='_compute_business_metrics', store=True)
    cost_per_purchase = fields.Monetary(currency_field='currency_id', compute='_compute_business_metrics', store=True)
    roas = fields.Float(string='ROAS', compute='_compute_business_metrics', store=True)

    actions_json = fields.Json()
    action_values_json = fields.Json()
    cost_per_action_json = fields.Json()
    purchase_roas_json = fields.Json()
    breakdown_type = fields.Char(index=True)
    breakdown_value = fields.Char(index=True)
    raw_payload = fields.Json(readonly=True)

    # _sql_constraints = [
    #     (
    #         'meta_insight_unique_grain',
    #         'unique(company_id, date_start, ad_account_id, meta_campaign_id, meta_adset_id, meta_ad_id, breakdown_type, breakdown_value)',
    #         'Insight already exists for this date, ad and breakdown.'
    #     ),
    # ]

    @api.depends('date_start', 'campaign_name', 'ad_name')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s - %s - %s' % (rec.date_start or '', rec.campaign_name or 'Campaign', rec.ad_name or 'Ad')

    @api.depends('spend', 'leads', 'purchases', 'purchase_value')
    def _compute_business_metrics(self):
        for rec in self:
            rec.cost_per_lead = rec.spend / rec.leads if rec.leads else 0.0
            rec.cost_per_purchase = rec.spend / rec.purchases if rec.purchases else 0.0
            rec.roas = rec.purchase_value / rec.spend if rec.spend else 0.0

    @api.model
    def _sync_from_account(self, account, since, until, level='ad'):
        fields_param = ','.join([
            'date_start', 'date_stop', 'account_id',
            'campaign_id', 'campaign_name', 'adset_id', 'adset_name', 'ad_id', 'ad_name',
            'impressions', 'reach', 'frequency', 'spend', 'clicks', 'inline_link_clicks',
            'ctr', 'cpc', 'cpm', 'cpp', 'actions', 'action_values', 'cost_per_action_type', 'purchase_roas'
        ])
        params = {
            'level': level,
            'time_increment': 1,
            'fields': fields_param,
            'time_range': json.dumps({'since': since, 'until': until}),
            'limit': 500,
        }
        for item in self._meta_graph_get_paged(account.config_id, '%s/insights' % account._act_path(), params=params, timeout=180):
            self._upsert_from_meta(account, item)
        return True

    @api.model
    def _upsert_from_meta(self, account, item, breakdown_type=False, breakdown_value=False):
        campaign = self.env['meta.campaign'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_campaign_id', '=', item.get('campaign_id')),
        ], limit=1)
        adset = self.env['meta.ad.set'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_adset_id', '=', item.get('adset_id')),
        ], limit=1)
        ad = self.env['meta.ad'].search([
            ('company_id', '=', account.company_id.id),
            ('meta_ad_id', '=', item.get('ad_id')),
        ], limit=1)

        actions = item.get('actions') or []
        action_values = item.get('action_values') or []
        lead_names = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
        purchase_names = {'purchase', 'offsite_conversion.fb_pixel_purchase', 'omni_purchase'}
        leads = int(self._get_action_value(actions, lead_names))
        purchases = int(self._get_action_value(actions, purchase_names))
        purchase_value = self._get_action_value(action_values, purchase_names)

        vals = {
            'company_id': account.company_id.id,
            'config_id': account.config_id.id,
            'ad_account_id': account.id,
            'date_start': item.get('date_start'),
            'date_stop': item.get('date_stop'),
            'campaign_id': campaign.id or False,
            'adset_id': adset.id or False,
            'ad_id': ad.id or False,
            'meta_campaign_id': item.get('campaign_id') or '',
            'meta_adset_id': item.get('adset_id') or '',
            'meta_ad_id': item.get('ad_id') or '',
            'campaign_name': item.get('campaign_name'),
            'adset_name': item.get('adset_name'),
            'ad_name': item.get('ad_name'),
            'impressions': self._int_value(item.get('impressions')),
            'reach': self._int_value(item.get('reach')),
            'frequency': self._float_value(item.get('frequency')),
            'spend': self._float_value(item.get('spend')),
            'clicks': self._int_value(item.get('clicks')),
            'inline_link_clicks': self._int_value(item.get('inline_link_clicks')),
            'ctr': self._float_value(item.get('ctr')),
            'cpc': self._float_value(item.get('cpc')),
            'cpm': self._float_value(item.get('cpm')),
            'cpp': self._float_value(item.get('cpp')),
            'leads': leads,
            'purchases': purchases,
            'purchase_value': purchase_value,
            'actions_json': actions,
            'action_values_json': action_values,
            'cost_per_action_json': item.get('cost_per_action_type'),
            'purchase_roas_json': item.get('purchase_roas'),
            'breakdown_type': breakdown_type or '',
            'breakdown_value': breakdown_value or '',
            'raw_payload': item,
        }
        domain = [
            ('company_id', '=', account.company_id.id),
            ('date_start', '=', item.get('date_start')),
            ('ad_account_id', '=', account.id),
            ('meta_campaign_id', '=', vals['meta_campaign_id']),
            ('meta_adset_id', '=', vals['meta_adset_id']),
            ('meta_ad_id', '=', vals['meta_ad_id']),
            ('breakdown_type', '=', vals['breakdown_type']),
            ('breakdown_value', '=', vals['breakdown_value']),
        ]
        existing = self.search(domain, limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
