# -*- coding: utf-8 -*-
import calendar
import hashlib
import uuid

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MetaConversionEvent(models.Model):
    _name = 'meta.conversion.event'
    _description = 'Meta Conversions API Event'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'meta.api.mixin']
    _order = 'create_date desc'

    name = fields.Char(required=True, default=lambda self: _('New Conversion Event'))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', required=True, ondelete='cascade', index=True)
    pixel_id = fields.Char(required=True, index=True, help='Meta Pixel/Dataset ID.')

    event_name = fields.Selection([
        ('Lead', 'Lead'),
        ('Contact', 'Contact'),
        ('CompleteRegistration', 'Complete Registration'),
        ('InitiateCheckout', 'Initiate Checkout'),
        ('AddToCart', 'Add To Cart'),
        ('Purchase', 'Purchase'),
        ('Subscribe', 'Subscribe'),
        ('Schedule', 'Schedule'),
        ('SubmitApplication', 'Submit Application'),
    ], required=True, default='Lead', tracking=True)
    event_id = fields.Char(required=True, index=True, copy=False)
    event_time = fields.Datetime(required=True, default=fields.Datetime.now)
    action_source = fields.Selection([
        ('website', 'Website'),
        ('app', 'App'),
        ('phone_call', 'Phone Call'),
        ('chat', 'Chat'),
        ('email', 'Email'),
        ('physical_store', 'Physical Store'),
        ('system_generated', 'System Generated'),
        ('business_messaging', 'Business Messaging'),
    ], required=True, default='website')

    partner_id = fields.Many2one('res.partner', index=True)
    lead_id = fields.Many2one('crm.lead', index=True)
    sale_order_id = fields.Many2one('sale.order', index=True)
    invoice_id = fields.Many2one('account.move', index=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, required=True)
    value = fields.Monetary(currency_field='currency_id')

    user_data_json = fields.Json()
    custom_data_json = fields.Json()
    status = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)
    response_json = fields.Json(readonly=True)
    retry_count = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)
    sent_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('event_id'):
                vals['event_id'] = str(uuid.uuid4())
            if vals.get('name') in (False, _('New Conversion Event')):
                vals['name'] = '%s - %s' % (vals.get('event_name') or 'Event', vals['event_id'])
        return super().create(vals_list)

    def action_prepare_user_data(self):
        for rec in self:
            rec.user_data_json = rec._build_user_data()
            rec.custom_data_json = rec._build_custom_data()
            rec.status = 'ready'
        return True

    def action_send(self):
        for rec in self:
            if not rec.user_data_json:
                rec.action_prepare_user_data()
            payload = {'data': [rec._to_meta_payload()]}
            try:
                response = rec._meta_graph_post(rec.config_id, '%s/events' % rec.pixel_id, payload=payload, timeout=120)
                rec.write({
                    'status': 'sent',
                    'response_json': response,
                    'last_error': False,
                    'sent_at': fields.Datetime.now(),
                })
                rec.message_post(body=_('Conversion event sent to Meta successfully.'))
            except Exception as exc:
                rec.write({
                    'status': 'failed',
                    'retry_count': rec.retry_count + 1,
                    'last_error': str(exc),
                })
                raise
        return True

    def action_cancel(self):
        self.write({'status': 'cancelled'})

    @api.model
    def cron_send_ready_events(self, limit=50):
        events = self.search([('status', 'in', ['ready', 'failed']), ('retry_count', '<', 5)], limit=limit, order='create_date asc')
        for event in events:
            try:
                event.action_send()
            except Exception:
                # keep cron alive; error is stored on each event
                continue

    def _to_meta_payload(self):
        self.ensure_one()
        event_dt = fields.Datetime.to_datetime(self.event_time)
        return {
            'event_name': self.event_name,
            'event_time': int(calendar.timegm(event_dt.utctimetuple())),
            'event_id': self.event_id,
            'action_source': self.action_source,
            'user_data': self.user_data_json or {},
            'custom_data': self.custom_data_json or {},
        }

    def _build_user_data(self):
        self.ensure_one()
        partner = self.partner_id or self.lead_id.partner_id or self.sale_order_id.partner_id or self.invoice_id.partner_id
        data = {}
        if partner.email:
            data['em'] = [self._sha256(partner.email)]
        if partner.phone or partner.mobile:
            data['ph'] = [self._sha256(partner.phone or partner.mobile)]
        if partner.city:
            data['ct'] = [self._sha256(partner.city)]
        if partner.zip:
            data['zp'] = [self._sha256(partner.zip)]
        if partner.country_id and partner.country_id.code:
            data['country'] = [self._sha256(partner.country_id.code)]
        return data

    def _build_custom_data(self):
        self.ensure_one()
        data = {
            'currency': self.currency_id.name,
            'value': self.value or 0.0,
        }
        content_ids = []
        if self.sale_order_id:
            content_ids = [line.product_id.default_code or str(line.product_id.id) for line in self.sale_order_id.order_line if line.product_id]
        elif self.invoice_id:
            content_ids = [line.product_id.default_code or str(line.product_id.id) for line in self.invoice_id.invoice_line_ids if line.product_id]
        if content_ids:
            data.update({'content_ids': content_ids, 'content_type': 'product'})
        return data

    @staticmethod
    def _sha256(value):
        if not value:
            return False
        normalized = str(value).strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @api.model
    def create_purchase_event_from_sale_order(self, order, config, pixel_id):
        if not order:
            raise UserError(_('Sale order is required.'))
        return self.create({
            'name': 'Purchase - %s' % order.name,
            'company_id': order.company_id.id,
            'config_id': config.id,
            'pixel_id': pixel_id,
            'event_name': 'Purchase',
            'event_id': '%s-Purchase' % order.name,
            'partner_id': order.partner_id.id,
            'sale_order_id': order.id,
            'currency_id': order.currency_id.id,
            'value': order.amount_total,
            'status': 'ready',
        })
