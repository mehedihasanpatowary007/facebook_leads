# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import models, fields, api, _


class MetaAdAccount(models.Model):
    _name = 'meta.ad.account'
    _description = 'Meta Ad Account'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)

    meta_account_id = fields.Char(required=True, index=True, help='Numeric Meta ad account id without act_ prefix.')
    display_account_id = fields.Char(required=True, index=True, help='Meta ad account id with act_ prefix.')
    account_status = fields.Char(index=True)
    disable_reason = fields.Char()
    currency = fields.Char(help='Meta account currency code, for example USD or BDT.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, required=True)
    timezone_name = fields.Char()
    amount_spent = fields.Monetary(currency_field='currency_id')
    balance = fields.Monetary(currency_field='currency_id')
    spend_cap = fields.Monetary(currency_field='currency_id')
    business_id = fields.Char()
    last_sync_at = fields.Datetime(readonly=True)
    raw_payload = fields.Json(readonly=True)

    campaign_ids = fields.One2many('meta.campaign', 'ad_account_id')
    campaign_count = fields.Integer(compute='_compute_counts')
    ad_set_count = fields.Integer(compute='_compute_counts')
    ad_count = fields.Integer(compute='_compute_counts')

    # _sql_constraints = [
    #     ('meta_ad_account_company_unique', 'unique(company_id, meta_account_id)', 'This Meta ad account already exists for this company.'),
    # ]

    @api.depends('campaign_ids')
    def _compute_counts(self):
        Campaign = self.env['meta.campaign']
        AdSet = self.env['meta.ad.set']
        Ad = self.env['meta.ad']
        for rec in self:
            rec.campaign_count = Campaign.search_count([('ad_account_id', '=', rec.id)])
            rec.ad_set_count = AdSet.search_count([('ad_account_id', '=', rec.id)])
            rec.ad_count = Ad.search_count([('ad_account_id', '=', rec.id)])

    @api.model
    def _sync_from_config(self, config):
        fields_param = ','.join([
            'id', 'name', 'account_status', 'disable_reason', 'currency', 'timezone_name',
            'amount_spent', 'balance', 'spend_cap', 'business'
        ])
        for item in self._meta_graph_get_paged(config, 'me/adaccounts', params={'fields': fields_param, 'limit': 100}):
            self._upsert_from_meta(config, item)
        return True

    @api.model
    def _upsert_from_meta(self, config, item):
        raw_id = item.get('id') or ''
        meta_account_id = raw_id.replace('act_', '')
        display_account_id = raw_id if raw_id.startswith('act_') else 'act_%s' % meta_account_id
        currency = self.env['res.currency'].search([('name', '=', item.get('currency'))], limit=1) or config.currency_id
        vals = {
            'name': item.get('name') or display_account_id,
            'company_id': config.company_id.id,
            'config_id': config.id,
            'meta_account_id': meta_account_id,
            'display_account_id': display_account_id,
            'account_status': str(item.get('account_status') or ''),
            'disable_reason': str(item.get('disable_reason') or ''),
            'currency': item.get('currency'),
            'currency_id': currency.id,
            'timezone_name': item.get('timezone_name'),
            'amount_spent': self._meta_amount_to_float(item.get('amount_spent')),
            'balance': self._meta_amount_to_float(item.get('balance')),
            'spend_cap': self._meta_amount_to_float(item.get('spend_cap')),
            'business_id': (item.get('business') or {}).get('id') if isinstance(item.get('business'), dict) else False,
            'last_sync_at': fields.Datetime.now(),
            'raw_payload': item,
        }
        existing = self.search([('company_id', '=', config.company_id.id), ('meta_account_id', '=', meta_account_id)], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    def _act_path(self):
        self.ensure_one()
        return self.display_account_id or ('act_%s' % self.meta_account_id)

    def action_sync_campaigns(self):
        for account in self:
            account.env['meta.campaign']._sync_from_account(account)
        return True

    def action_sync_ad_sets(self):
        for account in self:
            account.env['meta.ad.set']._sync_from_account(account)
        return True

    def action_sync_creatives_and_ads(self):
        for account in self:
            account.env['meta.ad']._sync_from_account(account)
        return True

    def action_sync_recent_insights(self, days=7):
        for account in self:
            since = date.today() - timedelta(days=max(days, 1))
            until = date.today()
            account.env['meta.ads.insight']._sync_from_account(account, since=since.isoformat(), until=until.isoformat())
        return True
