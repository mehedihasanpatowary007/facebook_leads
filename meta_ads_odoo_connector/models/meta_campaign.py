# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MetaCampaign(models.Model):
    _name = 'meta.campaign'
    _description = 'Meta Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('meta.ad.account', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='ad_account_id.currency_id', store=True, readonly=True)

    meta_campaign_id = fields.Char(required=True, index=True)
    objective = fields.Char(index=True)
    status = fields.Char(index=True, tracking=True)
    effective_status = fields.Char(index=True)
    buying_type = fields.Char()
    start_time = fields.Datetime()
    stop_time = fields.Datetime()
    daily_budget = fields.Monetary(currency_field='currency_id')
    lifetime_budget = fields.Monetary(currency_field='currency_id')
    spend_cap = fields.Monetary(currency_field='currency_id')
    special_ad_categories = fields.Json()
    utm_campaign_id = fields.Many2one('utm.campaign', string='Odoo UTM Campaign')
    last_sync_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    ad_set_ids = fields.One2many('meta.ad.set', 'campaign_id')
    ad_set_count = fields.Integer(compute='_compute_counts')
    ad_count = fields.Integer(compute='_compute_counts')
    insight_count = fields.Integer(compute='_compute_counts')

    # _sql_constraints = [
    #     ('meta_campaign_company_unique', 'unique(company_id, meta_campaign_id)', 'This Meta campaign already exists for this company.'),
    # ]

    @api.depends('ad_set_ids')
    def _compute_counts(self):
        AdSet = self.env['meta.ad.set']
        Ad = self.env['meta.ad']
        Insight = self.env['meta.ads.insight']
        for rec in self:
            rec.ad_set_count = AdSet.search_count([('campaign_id', '=', rec.id)])
            rec.ad_count = Ad.search_count([('campaign_id', '=', rec.id)])
            rec.insight_count = Insight.search_count([('campaign_id', '=', rec.id)])

    @api.model
    def _sync_from_account(self, account):
        fields_param = ','.join([
            'id', 'name', 'objective', 'status', 'effective_status', 'buying_type',
            'start_time', 'stop_time', 'daily_budget', 'lifetime_budget', 'spend_cap',
            'special_ad_categories'
        ])
        for item in self._meta_graph_get_paged(account.config_id, '%s/campaigns' % account._act_path(), params={
            'fields': fields_param,
            'limit': 100,
        }):
            self._upsert_from_meta(account, item)
        return True

    @api.model
    def _upsert_from_meta(self, account, item):
        vals = {
            'name': item.get('name') or item.get('id'),
            'company_id': account.company_id.id,
            'config_id': account.config_id.id,
            'ad_account_id': account.id,
            'meta_campaign_id': item.get('id'),
            'objective': item.get('objective'),
            'status': item.get('status'),
            'effective_status': item.get('effective_status'),
            'buying_type': item.get('buying_type'),
            'start_time': item.get('start_time'),
            'stop_time': item.get('stop_time'),
            'daily_budget': self._meta_amount_to_float(item.get('daily_budget')),
            'lifetime_budget': self._meta_amount_to_float(item.get('lifetime_budget')),
            'spend_cap': self._meta_amount_to_float(item.get('spend_cap')),
            'special_ad_categories': item.get('special_ad_categories'),
            'last_sync_at': fields.Datetime.now(),
            'raw_payload': item,
        }
        existing = self.search([('company_id', '=', account.company_id.id), ('meta_campaign_id', '=', item.get('id'))], limit=1)
        if existing:
            existing.write(vals)
            return existing
        campaign = self.create(vals)
        if not campaign.utm_campaign_id:
            utm = self.env['utm.campaign'].search([('name', '=', campaign.name)], limit=1)
            if not utm:
                utm = self.env['utm.campaign'].create({'name': campaign.name})
            campaign.utm_campaign_id = utm.id
        return campaign
