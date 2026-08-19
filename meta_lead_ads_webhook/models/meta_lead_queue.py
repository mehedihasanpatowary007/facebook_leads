# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaLeadQueue(models.Model):
    _name = 'meta.lead.queue'
    _description = 'Meta Lead Ads Queue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    connection_id = fields.Many2one('meta.lead.connection', index=True, ondelete='set null')
    company_id = fields.Many2one(
        'res.company',
        related='connection_id.company_id',
        store=True,
        readonly=True,
    )
    webhook_event_id = fields.Many2one('meta.lead.webhook.event', ondelete='set null', index=True)

    leadgen_id = fields.Char(string='LeadGen ID', required=True, index=True, tracking=True)
    form_id = fields.Char(string='Form ID', index=True)
    page_id = fields.Char(string='Page ID', index=True)
    ad_id = fields.Char(string='Ad ID', index=True)
    adset_id = fields.Char(string='Ad Set ID', index=True)
    campaign_id = fields.Char(string='Campaign ID', index=True)

    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('duplicate', 'Duplicate'),
            ('retry', 'Retry'),
            ('failed', 'Failed'),
            ('ignored', 'Ignored'),
        ],
        default='pending',
        required=True,
        tracking=True,
        index=True,
    )
    retry_count = fields.Integer(default=0, tracking=True)
    next_retry_at = fields.Datetime(index=True)
    processed_at = fields.Datetime()
    last_error = fields.Text()

    payload_json = fields.Json(string='Webhook Payload')
    lead_data_json = fields.Json(string='Fetched Lead Data')
    field_data_json = fields.Json(string='Lead Field Data')

    crm_lead_id = fields.Many2one('crm.lead', string='CRM Lead', readonly=True, index=True)

    # _sql_constraints = [
    #     ('leadgen_id_unique', 'unique(leadgen_id)', 'This Meta LeadGen ID is already queued.'),
    # ]

    @api.depends('leadgen_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.leadgen_id and 'Meta Lead %s' % rec.leadgen_id or 'Meta Lead'

    def action_process_now(self):
        for rec in self:
            rec._process_one()
        return True

    def action_retry(self):
        self.write({
            'state': 'pending',
            'last_error': False,
            'next_retry_at': False,
        })
        return True

    def action_open_crm_lead(self):
        self.ensure_one()
        if not self.crm_lead_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Lead'),
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.crm_lead_id.id,
        }

    @api.model
    def _cron_process_pending_leads(self):
        return self._process_pending()

    @api.model
    def _process_pending(self, connection=None, limit=50):
        now = fields.Datetime.now()
        domain = [
            ('state', 'in', ['pending', 'retry']),
            '|',
            ('next_retry_at', '=', False),
            ('next_retry_at', '<=', now),
        ]
        if connection:
            domain.append(('connection_id', '=', connection.id))
        records = self.search(domain, limit=limit, order='create_date asc, id asc')
        processed = 0
        for record in records:
            try:
                record._process_one()
                processed += 1
            except Exception:
                _logger.exception('Failed processing Meta lead queue %s', record.id)
        return processed

    def _process_one(self):
        self.ensure_one()
        if self.state in ('done', 'duplicate', 'ignored'):
            return True
        self.write({'state': 'processing'})
        try:
            connection = self._get_connection()
            if not connection:
                raise UserError(_('No active Meta Lead Ads connection was found for page %s.') % (self.page_id or ''))

            lead_payload = connection._graph_get(
                self.leadgen_id,
                params={
                    'fields': ','.join([
                        'id',
                        'created_time',
                        'field_data',
                        'ad_id',
                        'ad_name',
                        'adset_id',
                        'adset_name',
                        'campaign_id',
                        'campaign_name',
                        'form_id',
                        'platform',
                        'is_organic',
                    ]),
                },
            )
            self.write({
                'connection_id': connection.id,
                'lead_data_json': lead_payload,
                'field_data_json': lead_payload.get('field_data') or [],
                'form_id': lead_payload.get('form_id') or self.form_id,
                'ad_id': lead_payload.get('ad_id') or self.ad_id,
                'adset_id': lead_payload.get('adset_id') or self.adset_id,
                'campaign_id': lead_payload.get('campaign_id') or self.campaign_id,
            })

            if not connection.auto_create_crm_lead:
                self.write({
                    'state': 'ignored',
                    'processed_at': fields.Datetime.now(),
                    'last_error': _('Connection is configured not to auto-create CRM leads.'),
                })
                return True

            crm_lead = self._create_or_link_crm_lead(connection, lead_payload)
            state = 'done' if crm_lead else 'ignored'
            self.write({
                'state': state,
                'crm_lead_id': crm_lead.id if crm_lead else False,
                'processed_at': fields.Datetime.now(),
                'last_error': False,
            })
            return True
        except Exception as exc:
            self._handle_processing_error(exc)
            raise

    def _get_connection(self):
        self.ensure_one()
        connection = self.connection_id
        if connection and connection.active:
            return connection
        domain = [('active', '=', True)]
        if self.page_id:
            domain.append(('page_id', '=', self.page_id))
        return self.env['meta.lead.connection'].sudo().search(domain, limit=1)

    def _handle_processing_error(self, exc):
        self.ensure_one()
        connection = self.connection_id
        max_retry = connection.max_retry_count if connection else 5
        retry_delay = connection.retry_delay_minutes if connection else 10
        retry_count = self.retry_count + 1
        final_failed = retry_count >= max_retry
        self.write({
            'state': 'failed' if final_failed else 'retry',
            'retry_count': retry_count,
            'next_retry_at': False if final_failed else fields.Datetime.now() + timedelta(minutes=retry_delay),
            'last_error': str(exc),
        })

    def _create_or_link_crm_lead(self, connection, lead_payload):
        self.ensure_one()
        Lead = self.env['crm.lead'].sudo().with_company(connection.company_id)

        existing = Lead.search([('meta_leadgen_id', '=', self.leadgen_id)], limit=1)
        if existing:
            self.write({'state': 'duplicate', 'crm_lead_id': existing.id})
            return existing if connection.duplicate_strategy == 'link' else False

        field_values = self._field_data_to_dict(lead_payload.get('field_data') or [])
        if connection.duplicate_strategy == 'link':
            existing = self._find_existing_lead_by_contact(field_values, Lead)
            if existing:
                existing.write({
                    'meta_leadgen_id': self.leadgen_id,
                    'meta_form_id': lead_payload.get('form_id') or self.form_id,
                    'meta_page_id': self.page_id,
                    'meta_raw_payload': lead_payload,
                    'meta_queue_id': self.id,
                })
                existing.message_post(body=_('Linked to Meta LeadGen ID %s from webhook queue.') % self.leadgen_id)
                return existing

        mapping = self._get_form_mapping(connection, lead_payload.get('form_id') or self.form_id)
        values = self._prepare_crm_lead_values(connection, mapping, lead_payload, field_values)
        crm_lead = Lead.create(values)
        crm_lead.message_post(body=_('Created from Meta Lead Ads webhook. LeadGen ID: %s') % self.leadgen_id)
        return crm_lead

    def _get_form_mapping(self, connection, form_id):
        if not form_id:
            return self.env['meta.lead.form.mapping']
        return self.env['meta.lead.form.mapping'].sudo().search([
            ('connection_id', '=', connection.id),
            ('meta_form_id', '=', form_id),
            ('active', '=', True),
        ], limit=1)

    @staticmethod
    def _field_data_to_dict(field_data):
        values = {}
        for item in field_data or []:
            name = item.get('name')
            raw_values = item.get('values') or []
            if not name:
                continue
            if len(raw_values) == 1:
                values[name] = raw_values[0]
            else:
                values[name] = ', '.join(str(v) for v in raw_values)
        return values

    def _find_existing_lead_by_contact(self, field_values, Lead):
        email = self._first_value(field_values, ['email', 'email_address'])
        phone = self._first_value(field_values, ['phone_number', 'phone', 'mobile', 'mobile_phone'])
        domain = []
        if email:
            domain = [('email_from', '=ilike', email)]
        if phone:
            phone_domain = ['|', ('phone', '=ilike', phone), ('mobile', '=ilike', phone)]
            domain = ['|'] + domain + phone_domain if domain else phone_domain
        if not domain:
            return Lead.browse()
        return Lead.search(domain, limit=1)

    @staticmethod
    def _first_value(values, keys):
        for key in keys:
            if values.get(key):
                return values.get(key)
        return False

    def _prepare_crm_lead_values(self, connection, mapping, lead_payload, field_values):
        self.ensure_one()
        Lead = self.env['crm.lead']
        full_name = self._first_value(field_values, ['full_name', 'name'])
        first_name = self._first_value(field_values, ['first_name'])
        last_name = self._first_value(field_values, ['last_name'])
        contact_name = full_name or ' '.join(part for part in [first_name, last_name] if part).strip()
        email = self._first_value(field_values, ['email', 'email_address'])
        phone = self._first_value(field_values, ['phone_number', 'phone', 'mobile', 'mobile_phone'])
        company_name = self._first_value(field_values, ['company_name', 'company'])

        lead_name = contact_name or email or phone or _('Meta Lead %s') % self.leadgen_id
        description = self._build_description(lead_payload, field_values)

        values = {
            'name': _('Meta Lead - %s') % lead_name,
            'description': description,
            'company_id': connection.company_id.id,
            'meta_leadgen_id': self.leadgen_id,
            'meta_form_id': lead_payload.get('form_id') or self.form_id,
            'meta_page_id': self.page_id or connection.page_id,
            'meta_ad_id': lead_payload.get('ad_id') or self.ad_id,
            'meta_ad_name': lead_payload.get('ad_name'),
            'meta_adset_id': lead_payload.get('adset_id') or self.adset_id,
            'meta_adset_name': lead_payload.get('adset_name'),
            'meta_campaign_id': lead_payload.get('campaign_id') or self.campaign_id,
            'meta_campaign_name': lead_payload.get('campaign_name'),
            'meta_platform': lead_payload.get('platform'),
            'meta_is_organic': bool(lead_payload.get('is_organic')),
            'meta_created_time': self._parse_meta_datetime(lead_payload.get('created_time')),
            'meta_raw_payload': lead_payload,
            'meta_queue_id': self.id,
        }

        self._safe_set(values, Lead, 'contact_name', contact_name)
        self._safe_set(values, Lead, 'partner_name', company_name or contact_name)
        self._safe_set(values, Lead, 'email_from', email)
        self._safe_set(values, Lead, 'phone', phone)
        self._safe_set(values, Lead, 'mobile', phone)
        self._safe_set(values, Lead, 'city', self._first_value(field_values, ['city']))
        self._safe_set(values, Lead, 'zip', self._first_value(field_values, ['zip', 'post_code', 'postal_code']))
        self._safe_set(values, Lead, 'street', self._first_value(field_values, ['street_address', 'address']))
        self._safe_set(values, Lead, 'function', self._first_value(field_values, ['job_title', 'position']))
        self._safe_set(values, Lead, 'type', 'lead')

        target_values = mapping.get_target_values() if mapping else {
            'team_id': connection.default_team_id.id or False,
            'user_id': connection.default_user_id.id or False,
            'source_id': connection.default_source_id.id or False,
            'medium_id': connection.default_medium_id.id or False,
            'campaign_id': False,
            'tag_ids': [(6, 0, connection.default_tag_ids.ids)],
        }
        for key, value in target_values.items():
            if key in Lead._fields and value:
                values[key] = value

        if mapping:
            for line in mapping.field_map_line_ids:
                value = field_values.get(line.meta_field_name)
                if value and line.odoo_field_name in Lead._fields:
                    values[line.odoo_field_name] = value

        return values

    @staticmethod
    def _safe_set(values, model, field_name, value):
        if value and field_name in model._fields:
            values[field_name] = value

    def _build_description(self, lead_payload, field_values):
        lines = [
            _('Source: Meta Lead Ads Webhook'),
            _('LeadGen ID: %s') % self.leadgen_id,
        ]
        if lead_payload.get('campaign_name'):
            lines.append(_('Campaign: %s') % lead_payload.get('campaign_name'))
        if lead_payload.get('adset_name'):
            lines.append(_('Ad Set: %s') % lead_payload.get('adset_name'))
        if lead_payload.get('ad_name'):
            lines.append(_('Ad: %s') % lead_payload.get('ad_name'))
        lines.append('')
        lines.append(_('Submitted Fields:'))
        for key, value in field_values.items():
            lines.append('%s: %s' % (key, value))
        lines.append('')
        lines.append(_('Raw Lead Data:'))
        lines.append(json.dumps(lead_payload, indent=2, ensure_ascii=False))
        return '\n'.join(lines)

    @staticmethod
    def _parse_meta_datetime(value):
        if not value:
            return False
        try:
            # Meta commonly returns 2026-06-24T05:52:38+0000
            dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S%z')
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            try:
                value = value.replace('Z', '+00:00')
                dt = datetime.fromisoformat(value)
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except Exception:
                return False
