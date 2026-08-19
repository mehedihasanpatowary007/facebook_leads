# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class MetaLeadAdsWebhookController(http.Controller):
    """Public Meta Lead Ads webhook endpoint.

    Meta verification uses GET with hub.mode, hub.verify_token, hub.challenge.
    Meta lead notifications use POST with a JSON payload containing leadgen changes.
    """

    @http.route('/meta_lead_ads/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def verify_webhook(self, **kwargs):
        mode = kwargs.get('hub.mode')
        token = kwargs.get('hub.verify_token')
        challenge = kwargs.get('hub.challenge')

        connection = request.env['meta.lead.connection'].sudo().search([
            ('active', '=', True),
            ('webhook_verify_token', '=', token),
        ], limit=1)

        if mode == 'subscribe' and connection and challenge:
            return request.make_response(challenge, headers=[('Content-Type', 'text/plain')])

        return request.make_response('Forbidden', status=403, headers=[('Content-Type', 'text/plain')])

    @http.route('/meta_lead_ads/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_webhook(self, **kwargs):
        raw_body = request.httprequest.get_data() or b''
        raw_text = raw_body.decode('utf-8', errors='replace')
        signature_header = request.httprequest.headers.get('X-Hub-Signature-256') or ''
        payload = {}
        event = False
        connection = False

        try:
            payload = json.loads(raw_text or '{}')
            page_ids = self._extract_page_ids(payload)
            connection = self._find_connection(page_ids)
            signature_valid = self._signature_valid(connection, raw_body, signature_header)

            event = request.env['meta.lead.webhook.event'].sudo().create({
                'name': 'Meta Lead Ads Webhook %s' % fields.Datetime.now(),
                'connection_id': connection.id if connection else False,
                'object_type': payload.get('object'),
                'meta_page_id': page_ids[0] if page_ids else False,
                'signature_header': signature_header,
                'signature_valid': signature_valid,
                'payload_json': payload,
                'raw_body': raw_text,
                'state': 'received',
            })

            if connection and connection.enforce_signature and not signature_valid:
                event.write({
                    'state': 'failed',
                    'error_message': 'Invalid X-Hub-Signature-256 header.',
                })
                return self._json_response({'success': False, 'error': 'invalid_signature'}, status=403)

            queued_count = self._queue_leads(payload, event, connection)
            event.write({'state': 'queued' if queued_count else 'ignored'})
            return self._json_response({'success': True, 'queued': queued_count})
        except Exception as exc:
            _logger.exception('Meta Lead Ads webhook failed')
            try:
                values = {
                    'name': 'Meta Lead Ads Webhook Failed %s' % fields.Datetime.now(),
                    'connection_id': connection.id if connection else False,
                    'signature_header': signature_header,
                    'payload_json': payload or {},
                    'raw_body': raw_text,
                    'state': 'failed',
                    'error_message': str(exc),
                }
                if event:
                    event.sudo().write(values)
                else:
                    request.env['meta.lead.webhook.event'].sudo().create(values)
            except Exception:
                _logger.exception('Could not store failed Meta webhook event')
            return self._json_response({'success': False, 'error': str(exc)}, status=500)

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            status=status,
            headers=[('Content-Type', 'application/json')],
        )

    @staticmethod
    def _extract_page_ids(payload):
        page_ids = []
        for entry in payload.get('entry', []) or []:
            page_id = str(entry.get('id') or '')
            if page_id and page_id not in page_ids:
                page_ids.append(page_id)
            for change in entry.get('changes', []) or []:
                value = change.get('value') or {}
                value_page_id = str(value.get('page_id') or '')
                if value_page_id and value_page_id not in page_ids:
                    page_ids.append(value_page_id)
        return page_ids

    def _find_connection(self, page_ids):
        Connection = request.env['meta.lead.connection'].sudo()
        if page_ids:
            connection = Connection.search([('active', '=', True), ('page_id', 'in', page_ids)], limit=1)
            if connection:
                return connection
        return Connection.search([('active', '=', True)], limit=1)

    @staticmethod
    def _signature_valid(connection, raw_body, signature_header):
        if not connection or not connection.enforce_signature:
            return True
        if not connection.app_secret:
            return False
        if not signature_header or not signature_header.startswith('sha256='):
            return False
        expected = 'sha256=' + hmac.new(
            connection.app_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def _queue_leads(self, payload, event, default_connection):
        Queue = request.env['meta.lead.queue'].sudo()
        Connection = request.env['meta.lead.connection'].sudo()
        queued_count = 0

        for entry in payload.get('entry', []) or []:
            entry_page_id = str(entry.get('id') or '')
            connection = default_connection
            if entry_page_id:
                match = Connection.search([('active', '=', True), ('page_id', '=', entry_page_id)], limit=1)
                connection = match or connection

            for change in entry.get('changes', []) or []:
                if change.get('field') != 'leadgen':
                    continue
                value = change.get('value') or {}
                leadgen_id = str(value.get('leadgen_id') or '')
                if not leadgen_id:
                    continue
                page_id = str(value.get('page_id') or entry_page_id or '')
                existing = Queue.search([('leadgen_id', '=', leadgen_id)], limit=1)
                if existing:
                    if event and existing.webhook_event_id != event:
                        existing.write({'webhook_event_id': event.id})
                    continue

                queue = Queue.create({
                    'connection_id': connection.id if connection else False,
                    'webhook_event_id': event.id,
                    'leadgen_id': leadgen_id,
                    'form_id': value.get('form_id'),
                    'page_id': page_id,
                    'ad_id': value.get('ad_id'),
                    'adset_id': value.get('adset_id'),
                    'campaign_id': value.get('campaign_id'),
                    'payload_json': value,
                    'state': 'pending',
                })
                queued_count += 1
                if connection and connection.process_immediately:
                    try:
                        queue._process_one()
                    except Exception:
                        _logger.exception('Immediate processing failed for Meta LeadGen ID %s', leadgen_id)
        return queued_count
