# -*- coding: utf-8 -*-
from odoo import fields, models


class MetaLeadWebhookEvent(models.Model):
    _name = 'meta.lead.webhook.event'
    _description = 'Meta Lead Ads Webhook Event'
    _inherit = ['mail.thread']
    _order = 'received_at desc, id desc'

    name = fields.Char(default='Webhook Event', required=True)
    connection_id = fields.Many2one('meta.lead.connection', index=True, ondelete='set null')
    company_id = fields.Many2one(
        'res.company',
        related='connection_id.company_id',
        store=True,
        readonly=True,
    )
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    state = fields.Selection(
        [
            ('received', 'Received'),
            ('queued', 'Queued'),
            ('ignored', 'Ignored'),
            ('failed', 'Failed'),
        ],
        default='received',
        required=True,
        tracking=True,
        index=True,
    )
    object_type = fields.Char(string='Object')
    meta_page_id = fields.Char(string='Meta Page ID', index=True)
    signature_header = fields.Char()
    signature_valid = fields.Boolean(default=False)
    payload_json = fields.Json(string='Payload')
    raw_body = fields.Text(string='Raw Body')
    error_message = fields.Text()
    queue_ids = fields.One2many('meta.lead.queue', 'webhook_event_id', string='Queued Leads')
    queue_count = fields.Integer(compute='_compute_queue_count')

    def _compute_queue_count(self):
        for rec in self:
            rec.queue_count = len(rec.queue_ids)

    def action_open_queue(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Queued Leads',
            'res_model': 'meta.lead.queue',
            'view_mode': 'list,form',
            'domain': [('webhook_event_id', '=', self.id)],
        }
