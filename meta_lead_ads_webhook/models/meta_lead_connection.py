# -*- coding: utf-8 -*-
import json
import logging
from urllib.parse import urljoin

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaLeadConnection(models.Model):
    _name = 'meta.lead.connection'
    _description = 'Meta Lead Ads Connection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    api_version = fields.Char(
        string='Graph API Version',
        default='v25.0',
        required=True,
        help='Example: v25.0. Keep this aligned with your approved Meta app version.',
    )
    app_id = fields.Char(string='Meta App ID', tracking=True)
    app_secret = fields.Char(
        string='Meta App Secret',
        groups='meta_lead_ads_webhook.group_meta_lead_technical',
        copy=False,
    )
    page_id = fields.Char(
        string='Facebook Page ID',
        required=True,
        index=True,
        help='The Page ID subscribed to leadgen webhooks.',
    )
    page_access_token = fields.Char(
        string='Page Access Token',
        required=True,
        groups='meta_lead_ads_webhook.group_meta_lead_technical',
        copy=False,
        help='Token used to retrieve lead details from Graph API.',
    )
    webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        required=True,
        copy=False,
        help='Random secret you enter in Meta Webhook setup. Meta sends it during verification.',
    )
    enforce_signature = fields.Boolean(
        string='Validate X-Hub Signature',
        default=True,
        help='Recommended in production. Requires App Secret and Meta X-Hub-Signature-256 header.',
    )

    default_team_id = fields.Many2one('crm.team', string='Default Sales Team')
    default_user_id = fields.Many2one('res.users', string='Default Salesperson')
    default_source_id = fields.Many2one('utm.source', string='Default Source')
    default_medium_id = fields.Many2one('utm.medium', string='Default Medium')
    default_tag_ids = fields.Many2many('crm.tag', string='Default CRM Tags')

    auto_create_crm_lead = fields.Boolean(default=True)
    process_immediately = fields.Boolean(
        string='Process Immediately During Webhook',
        default=True,
        help='If enabled, Odoo fetches the full lead and creates the CRM lead during the webhook request. If disabled, the cron processes the queue shortly after.',
    )
    duplicate_strategy = fields.Selection(
        [
            ('skip', 'Skip Existing LeadGen ID'),
            ('link', 'Link To Existing Email/Phone Lead'),
            ('create', 'Always Create New Lead'),
        ],
        default='skip',
        required=True,
        help='Controls what happens when a duplicate lead is detected.',
    )
    max_retry_count = fields.Integer(default=5, required=True)
    retry_delay_minutes = fields.Integer(default=10, required=True)

    last_test_at = fields.Datetime(readonly=True)
    last_test_status = fields.Selection(
        [('success', 'Success'), ('failed', 'Failed')],
        readonly=True,
    )
    last_test_message = fields.Text(readonly=True)

    webhook_url = fields.Char(compute='_compute_webhook_url')

    # _sql_constraints = [
    #     ('page_id_company_unique', 'unique(page_id, company_id)', 'This Page ID is already configured for this company.'),
    # ]

    @api.depends('page_id')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.webhook_url = urljoin(base_url.rstrip('/') + '/', 'meta_lead_ads/webhook') if base_url else '/meta_lead_ads/webhook'

    def _graph_base_url(self):
        self.ensure_one()
        version = (self.api_version or '').strip().strip('/')
        return 'https://graph.facebook.com/%s/' % version

    def _graph_get(self, object_id, params=None, timeout=30):
        self.ensure_one()
        params = dict(params or {})
        params['access_token'] = self.page_access_token
        url = urljoin(self._graph_base_url(), str(object_id).strip('/'))
        _logger.debug('Meta GET %s params=%s', url, {k: v for k, v in params.items() if k != 'access_token'})
        response = requests.get(url, params=params, timeout=timeout)
        try:
            payload = response.json()
        except Exception:
            payload = {'raw_response': response.text}
        if response.status_code >= 400 or isinstance(payload, dict) and payload.get('error'):
            error = payload.get('error') if isinstance(payload, dict) else payload
            message = error.get('message') if isinstance(error, dict) else str(error)
            raise UserError(_('Meta API error: %s') % message)
        return payload

    def action_test_connection(self):
        for rec in self:
            try:
                payload = rec._graph_get(rec.page_id, params={'fields': 'id,name'})
                rec.write({
                    'last_test_at': fields.Datetime.now(),
                    'last_test_status': 'success',
                    'last_test_message': json.dumps(payload, indent=2, ensure_ascii=False),
                })
                rec.message_post(body=_('Meta Lead Ads connection test succeeded.'))
            except Exception as exc:
                rec.write({
                    'last_test_at': fields.Datetime.now(),
                    'last_test_status': 'failed',
                    'last_test_message': str(exc),
                })
                raise
        return True

    def action_process_pending_queue(self):
        self.ensure_one()
        return self.env['meta.lead.queue'].sudo()._process_pending(connection=self)

    def action_open_webhook_events(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Webhook Events'),
            'res_model': 'meta.lead.webhook.event',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }

    def action_open_lead_queue(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead Queue'),
            'res_model': 'meta.lead.queue',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }
