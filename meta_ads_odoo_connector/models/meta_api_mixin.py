# -*- coding: utf-8 -*-
import json
import logging
import time
from urllib.parse import urljoin

import requests

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaApiMixin(models.AbstractModel):
    """Small reusable Graph API client.

    Design notes:
    - Access tokens are never written to logs.
    - All calls are recorded in meta.api.log for support/debugging.
    - This v1 client intentionally supports safe read/reporting and CAPI sends.
    """

    _name = 'meta.api.mixin'
    _description = 'Meta Graph API Client Mixin'

    def _meta_graph_request(self, config, method, path, params=None, payload=None, timeout=90):
        self.ensure_one() if self and self._name != 'meta.api.mixin' else None
        if not config:
            raise UserError(_('Meta configuration is required.'))
        if not config.access_token:
            raise UserError(_('Meta access token is missing. Configure the connection first.'))

        method = method.upper()
        params = dict(params or {})
        params['access_token'] = config.access_token

        base_url = 'https://graph.facebook.com/%s/' % (config.api_version or 'v25.0')
        url = urljoin(base_url, path.lstrip('/'))

        log_vals = {
            'config_id': config.id,
            'method': method,
            'endpoint': path,
            'request_payload': self._safe_json({'params': {k: v for k, v in params.items() if k != 'access_token'}, 'payload': payload}),
            'status': 'draft',
            'company_id': config.company_id.id,
        }
        log = self.env['meta.api.log'].sudo().create(log_vals)
        started_at = time.time()

        try:
            if method == 'GET':
                response = requests.get(url, params=params, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, params=params, json=payload or {}, timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, params=params, timeout=timeout)
            else:
                raise UserError(_('Unsupported HTTP method: %s') % method)

            duration_ms = int((time.time() - started_at) * 1000)
            try:
                response_json = response.json()
            except ValueError:
                response_json = {'raw_text': response.text}

            status = 'success' if response.ok else 'failed'
            log.sudo().write({
                'status': status,
                'http_status': response.status_code,
                'duration_ms': duration_ms,
                'response_payload': self._safe_json(response_json),
                'error_message': False if response.ok else self._extract_meta_error(response_json),
            })

            if not response.ok:
                raise UserError(_('Meta API error: %s') % self._extract_meta_error(response_json))
            return response_json

        except requests.RequestException as exc:
            duration_ms = int((time.time() - started_at) * 1000)
            log.sudo().write({
                'status': 'failed',
                'duration_ms': duration_ms,
                'error_message': str(exc),
            })
            _logger.exception('Meta API request failed: %s %s', method, path)
            raise UserError(_('Meta API request failed: %s') % exc) from exc

    def _meta_graph_get(self, config, path, params=None, timeout=90):
        return self._meta_graph_request(config, 'GET', path, params=params, timeout=timeout)

    def _meta_graph_post(self, config, path, params=None, payload=None, timeout=90):
        return self._meta_graph_request(config, 'POST', path, params=params, payload=payload, timeout=timeout)

    def _meta_graph_get_paged(self, config, path, params=None, timeout=90, max_pages=50):
        """Yield records across cursor-paginated Graph API responses.

        We use the `after` cursor instead of the full `paging.next` URL so access
        tokens are not copied into Odoo logs.
        """
        page_params = dict(params or {})
        pages = 0
        while True:
            response = self._meta_graph_get(config, path, params=page_params, timeout=timeout)
            for item in response.get('data', []):
                yield item
            pages += 1
            if pages >= max_pages:
                break
            after = response.get('paging', {}).get('cursors', {}).get('after')
            if not after:
                break
            page_params['after'] = after

    @staticmethod
    def _extract_meta_error(response_json):
        error = response_json.get('error') if isinstance(response_json, dict) else None
        if not error:
            return json.dumps(response_json)[:1000]
        message = error.get('message') or error.get('error_user_msg') or str(error)
        code = error.get('code')
        subcode = error.get('error_subcode')
        return 'code=%s subcode=%s message=%s' % (code, subcode, message)

    @staticmethod
    def _safe_json(value):
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return {'raw': str(value)}

    @staticmethod
    def _meta_amount_to_float(value):
        """Meta budget fields are commonly returned in minor units.

        We keep raw_payload as source of truth. This helper gives business users a readable amount.
        """
        if value in (False, None, ''):
            return 0.0
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _float_value(value):
        if value in (False, None, ''):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _int_value(value):
        if value in (False, None, ''):
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _get_action_value(actions, names):
        if not actions:
            return 0.0
        if isinstance(names, str):
            names = {names}
        else:
            names = set(names)
        total = 0.0
        for action in actions:
            if action.get('action_type') in names:
                try:
                    total += float(action.get('value') or 0.0)
                except (TypeError, ValueError):
                    continue
        return total
