# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class MetaAdsConfig(models.Model):
    _name = 'meta.ads.config'
    _description = 'Meta Ads Connection'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True, readonly=True)

    api_version = fields.Char(default='v25.0', required=True, help='Graph/Marketing API version, for example v25.0.')
    app_id = fields.Char(groups='meta_ads_odoo_connector.group_meta_ads_administrator')
    app_secret = fields.Char(groups='meta_ads_odoo_connector.group_meta_ads_administrator')
    access_token = fields.Char(groups='meta_ads_odoo_connector.group_meta_ads_administrator')
    token_expires_at = fields.Datetime(groups='meta_ads_odoo_connector.group_meta_ads_administrator')
    business_id = fields.Char(index=True)

    auto_sync = fields.Boolean(default=True, tracking=True)
    sync_insights_days = fields.Integer(default=7, help='How many recent days should be refreshed during each automatic sync.')
    last_test_at = fields.Datetime(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    ad_account_ids = fields.One2many('meta.ad.account', 'config_id', string='Ad Accounts')
    ad_account_count = fields.Integer(compute='_compute_counts')
    campaign_count = fields.Integer(compute='_compute_counts')
    insight_count = fields.Integer(compute='_compute_counts')

    @api.depends('ad_account_ids')
    def _compute_counts(self):
        Account = self.env['meta.ad.account']
        Campaign = self.env['meta.campaign']
        Insight = self.env['meta.ads.insight']
        for rec in self:
            rec.ad_account_count = Account.search_count([('config_id', '=', rec.id)])
            rec.campaign_count = Campaign.search_count([('config_id', '=', rec.id)])
            rec.insight_count = Insight.search_count([('config_id', '=', rec.id)])

    def button_test_connection(self):
        for rec in self:
            response = rec._meta_graph_get(rec, 'me', params={'fields': 'id,name'})
            rec.write({'last_test_at': fields.Datetime.now(), 'last_error': False})
            rec.message_post(body=_('Meta connection test successful for: %s') % (response.get('name') or response.get('id')))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Meta Connection'),
                'message': _('Connection test completed successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_all(self):
        for rec in self:
            rec._sync_all()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Meta Sync'),
                'message': _('Sync completed. Check API Logs for details.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def _sync_all(self):
        for rec in self:
            try:
                rec.env['meta.ad.account']._sync_from_config(rec)
                accounts = rec.env['meta.ad.account'].search([('config_id', '=', rec.id), ('active', '=', True)])
                accounts.action_sync_campaigns()
                accounts.action_sync_ad_sets()
                accounts.action_sync_creatives_and_ads()
                accounts.action_sync_recent_insights(days=rec.sync_insights_days or 7)
                rec.write({'last_sync_at': fields.Datetime.now(), 'last_error': False})
            except Exception as exc:
                rec.write({'last_error': str(exc)})
                raise

    @api.model
    def cron_sync_active_configs(self):
        configs = self.search([('active', '=', True), ('auto_sync', '=', True)])
        configs._sync_all()
