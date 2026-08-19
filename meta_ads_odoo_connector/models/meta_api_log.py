# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MetaApiLog(models.Model):
    _name = 'meta.api.log'
    _description = 'Meta API Log'
    _order = 'create_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    config_id = fields.Many2one('meta.ads.config', ondelete='set null', index=True)
    method = fields.Char(required=True)
    endpoint = fields.Char(required=True, index=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('rate_limited', 'Rate Limited'),
    ], default='draft', index=True)
    http_status = fields.Integer(index=True)
    duration_ms = fields.Integer()
    request_payload = fields.Json()
    response_payload = fields.Json()
    error_message = fields.Text()

    @api.depends('method', 'endpoint', 'status')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s [%s]' % (rec.method or '', rec.endpoint or '', rec.status or '')
