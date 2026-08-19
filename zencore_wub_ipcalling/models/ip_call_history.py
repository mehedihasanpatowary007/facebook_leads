# -*- coding: utf-8 -*-
import json
import logging
import re
from urllib.parse import urljoin

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ZencoreWubIpCallHistory(models.Model):
    _name = 'zencore.wub.ip.call.history'
    _description = 'WUB IP Calling History'
    _order = 'called_at desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    lead_id = fields.Many2one(
        'crm.lead',
        string='Lead / Opportunity',
        index=True,
        ondelete='set null',
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='lead_id.partner_id',
        string='Customer',
        store=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        index=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    called_at = fields.Datetime(
        string='Called At',
        required=True,
        readonly=True,
        default=fields.Datetime.now,
    )
    operation_type = fields.Selection(
        selection=[
            ('click_to_call', 'Click to Call'),
        ],
        string='Operation',
        required=True,
        readonly=True,
        default='click_to_call',
        index=True,
    )
    is_active_call = fields.Boolean(
        string='Active Call',
        readonly=True,
        default=False,
        index=True,
        help='Enabled only while a successful click-to-call request is still active.',
    )
    agent_email = fields.Char(string='Agent Email', readonly=True, index=True)
    phone_number = fields.Char(string='Phone Number', readonly=True, index=True)
    calling_history_id = fields.Integer(
        string='External Calling History ID',
        readonly=True,
        index=True,
        help='The ID sent to the external API as calling_history_id. This module uses the Odoo log ID.',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('success', 'Success'),
            ('error', 'Error'),
        ],
        string='Status',
        required=True,
        readonly=True,
        default='draft',
        index=True,
    )
    http_status = fields.Integer(string='HTTP Status', readonly=True)
    api_status = fields.Char(string='API Status', readonly=True)
    response_code = fields.Char(string='Response Code', readonly=True, index=True)
    code_reason = fields.Char(string='Code Reason', readonly=True)
    result_reason = fields.Char(string='Result Reason', readonly=True)
    number = fields.Char(string='Returned Number', readonly=True)
    agent = fields.Char(string='Returned Agent', readonly=True)
    dial_extension = fields.Char(string='Dial Extension', readonly=True)
    error_message = fields.Text(string='Error Message', readonly=True)

    callback_received_at = fields.Datetime(string='Callback Received At', readonly=True)
    call_id = fields.Char(string='Dialer Call ID', readonly=True, index=True)
    call_time = fields.Datetime(string='Dialer Call Time', readonly=True)
    dialer_status = fields.Char(string='Dialer Status', readonly=True, index=True)
    call_status = fields.Char(string='Call Status', readonly=True, index=True)
    agent_id = fields.Char(string='Agent ID', readonly=True)
    agent_full_name = fields.Char(string='Agent Full Name', readonly=True)
    campaign = fields.Char(string='Campaign', readonly=True)
    length_in_sec = fields.Integer(string='Length (seconds)', readonly=True)
    term_reason = fields.Char(string='Termination Reason', readonly=True)
    recording_url = fields.Char(string='Recording URL', readonly=True)
    queue_seconds = fields.Integer(string='Queue Seconds', readonly=True)

    endpoint_url = fields.Char(string='Endpoint URL', readonly=True)
    request_method = fields.Char(string='Request Method', readonly=True, default='POST')
    request_format = fields.Char(string='Request Format', readonly=True)
    request_headers = fields.Text(string='Request Headers', readonly=True)
    request_payload = fields.Text(string='Request Payload', readonly=True)
    response_payload = fields.Text(string='Response Payload', readonly=True)
    callback_payload = fields.Text(string='Callback Payload', readonly=True)
    debug_message = fields.Text(
        string='Debug Message',
        readonly=True,
        help='Technical details about retries/fallbacks used by the API client.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('zencore.wub.ip.call.history') or _('New')
        return super().create(vals_list)

    @api.model
    def _get_api_config(self):
        """Return validated API configuration from ir.config_parameter."""
        icp = self.env['ir.config_parameter'].sudo()
        enabled = icp.get_param('zencore_wub_ipcalling.enabled', 'True')
        enabled = str(enabled).lower() in ('1', 'true', 'yes', 'y', 'on')

        base_url = (icp.get_param('zencore_wub_ipcalling.base_url', 'https://worlduni.ihelpbd.com') or '').strip()
        if base_url.rstrip('/') == 'http://worlduni.ihelpbd.com':
            base_url = 'https://worlduni.ihelpbd.com'
        endpoint_path = (icp.get_param('zencore_wub_ipcalling.endpoint_path', '/wub/api/click_to_call.php') or '').strip()
        authorization = (icp.get_param('zencore_wub_ipcalling.authorization', 'iHelpBD@Authorization@') or '').strip()
        timeout = icp.get_param('zencore_wub_ipcalling.timeout', '15')
        request_format = (icp.get_param('zencore_wub_ipcalling.request_format') or 'auto').strip().lower()
        if request_format not in ('auto', 'json', 'form'):
            request_format = 'auto'

        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 15
        timeout = max(timeout, 1)

        if not enabled:
            return {
                'enabled': False,
                'base_url': base_url,
                'endpoint_path': endpoint_path,
                'authorization': authorization,
                'timeout': timeout,
                'request_format': request_format,
                'endpoint_url': '',
            }

        endpoint_url = urljoin(base_url.rstrip('/') + '/', endpoint_path.lstrip('/'))
        return {
            'enabled': enabled,
            'base_url': base_url,
            'endpoint_path': endpoint_path,
            'authorization': authorization,
            'timeout': timeout,
            'request_format': request_format,
            'endpoint_url': endpoint_url,
        }

    @api.model
    def _normalize_phone_number(self, phone_number):
        """Normalize Bangladesh-style phone numbers for the API payload.

        The API document uses 01746733817. To reduce failed calls from CRM data,
        we remove spaces and common separators, and convert +880/880 numbers to 0XXXXXXXXXX.
        """
        phone_number = (phone_number or '').strip()
        cleaned = re.sub(r'[\s\-().]', '', phone_number)

        if cleaned.startswith('+880') and len(cleaned) == 14:
            cleaned = '0' + cleaned[4:]
        elif cleaned.startswith('880') and len(cleaned) == 13:
            cleaned = '0' + cleaned[3:]

        return cleaned


    @api.model
    def _get_lead_phone_value(self, lead):
        """Return the best available phone number from crm.lead safely.

        Odoo/community/custom CRM databases do not always expose the same phone
        fields. Some have phone only, some have mobile_phone, and some older
        implementations have mobile. Directly reading a missing field raises
        AttributeError, so always check lead._fields first.
        """
        lead.ensure_one()

        lead_field_candidates = [
            'mobile',
            'mobile_phone',
            'phone',
            'phone_sanitized',
        ]
        for field_name in lead_field_candidates:
            if field_name in lead._fields:
                value = lead[field_name]
                if value:
                    return value

        partner = lead.partner_id if 'partner_id' in lead._fields else False
        if partner:
            for field_name in ('mobile', 'phone'):
                if field_name in partner._fields:
                    value = partner[field_name]
                    if value:
                        return value

        return False

    @api.model
    def _base_headers(self, authorization, request_format):
        headers = {
            'Authorization': authorization,
            'Accept': 'application/json, text/plain, */*',
            'User-Agent': 'Odoo-19 Zencore-WUB-IPCalling',
        }
        if request_format == 'json':
            headers['Content-Type'] = 'application/json'
        else:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        return headers

    @api.model
    def _safe_headers_for_log(self, headers):
        safe_headers = dict(headers or {})
        if safe_headers.get('Authorization'):
            safe_headers['Authorization'] = '***masked***'
        return safe_headers

    @api.model
    def _parse_api_response(self, response):
        try:
            response_json = response.json()
            response_payload = json.dumps(response_json, indent=2, ensure_ascii=False)
        except ValueError:
            response_json = {}
            response_payload = response.text

        data = response_json.get('data') or {}
        api_status = response_json.get('status')
        response_code = response_json.get('response_code')
        result_reason = data.get('result_reason') or response_json.get('result_reason') or response.reason

        is_success = (
            response.status_code == 200
            and api_status == 'SUCCESS'
            and str(response_code) == '200'
            and data.get('status') == 'SUCCESS'
        )

        return {
            'response_json': response_json,
            'response_payload': response_payload,
            'data': data,
            'api_status': api_status,
            'response_code': response_code,
            'result_reason': result_reason,
            'is_success': is_success,
        }

    @api.model
    def _is_method_or_format_error(self, response, parsed):
        """Detect provider errors that usually mean wrong request method/content type.

        Some PHP click-to-call APIs document JSON but are implemented using $_POST,
        so application/json reaches the server but mandatory fields are not parsed.
        In those cases providers often return generic messages such as Method Not Allowed.
        """
        reason = (parsed.get('result_reason') or '').lower()
        body = (parsed.get('response_payload') or '').lower()
        return (
            response.status_code in (400, 405, 415)
            or 'method not allowed' in reason
            or 'method not allowed' in body
            or 'mandatory' in reason
            or 'required' in reason
            or 'not allowed' in reason
        )

    @api.model
    def _post_click_to_call(self, endpoint_url, payload, authorization, timeout, request_format):
        return self._post_api_request(
            endpoint_url,
            payload,
            authorization,
            timeout,
            request_format,
        )

    @api.model
    def _post_api_request(self, endpoint_url, payload, authorization, timeout, request_format):
        headers = self._base_headers(authorization, request_format)
        response = self._send_post_with_preserved_redirects(
            endpoint_url,
            payload,
            headers,
            timeout,
            request_format,
        )
        parsed = self._parse_api_response(response)
        return response, parsed, headers

    @api.model
    def _get_active_call(self, user=None, lead=None):
        """Return the latest active click-to-call record for a user/lead."""
        domain = [
            ('operation_type', '=', 'click_to_call'),
            ('state', '=', 'success'),
            ('is_active_call', '=', True),
        ]
        if user:
            domain.append(('user_id', '=', user.id))
        if lead:
            domain.append(('lead_id', '=', lead.id))
        return self.search(domain, order='called_at desc, id desc', limit=1)

    @api.model
    def _send_post_with_preserved_redirects(self, endpoint_url, payload, headers, timeout, request_format):
        """Send POST without allowing redirects to mutate it into GET.

        The iHelpBD endpoint may redirect HTTP/canonical URLs before reaching the
        PHP handler. requests follows 301/302/303 redirects by switching POST to
        GET, and this API then returns "Method Not Allowed." in a JSON body.
        """
        url = endpoint_url
        redirects = []

        for _redirect_count in range(5):
            if request_format == 'json':
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=False,
                )
            else:
                response = requests.post(
                    url,
                    data=payload,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=False,
                )

            if response.status_code not in (301, 302, 303, 307, 308):
                response.wub_redirects = redirects
                return response

            location = response.headers.get('Location') or response.headers.get('location')
            if not location:
                response.wub_redirects = redirects
                return response

            next_url = urljoin(response.url, location)
            redirects.append({
                'from': response.url,
                'to': next_url,
                'status': response.status_code,
            })
            url = next_url

        response.wub_redirects = redirects
        return response

    @api.model
    def send_click_to_call(self, lead):
        """Send click-to-call request for one CRM lead and store request/response log."""
        lead.ensure_one()

        config = self._get_api_config()
        if not config['enabled']:
            return self._notification(
                title=_('IP Calling Disabled'),
                message=_('WUB IP Calling is disabled in Settings.'),
                notification_type='warning',
                sticky=True,
            )

        if not config['base_url'] or not config['endpoint_path']:
            return self._notification(
                title=_('Missing API Configuration'),
                message=_('Please configure WUB IP Calling Base URL and Endpoint Path in Settings.'),
                notification_type='danger',
                sticky=True,
            )

        if not config['authorization']:
            return self._notification(
                title=_('Missing Authorization Key'),
                message=_('Please configure the WUB IP Calling Authorization Key in Settings.'),
                notification_type='danger',
                sticky=True,
            )

        agent_email = (self.env.user.ip_calling_mail or '').strip()
        if not agent_email:
            return self._notification(
                title=_('Missing Agent Email'),
                message=_('Please set IP Calling Mail on your user profile before making IP calls.'),
                notification_type='danger',
                sticky=True,
            )

        active_call = self._get_active_call(user=self.env.user)
        if active_call:
            return self._notification(
                title=_('IP Call Already Active'),
                message=_(
                    'You already have an active IP call for %(lead)s. Finish that call before starting another one.'
                ) % {
                    'lead': active_call.lead_id.display_name or _('another lead'),
                },
                notification_type='warning',
                sticky=True,
                reload=True,
            )

        phone_number = self._normalize_phone_number(self._get_lead_phone_value(lead))
        if not phone_number:
            return self._notification(
                title=_('Missing Phone Number'),
                message=_('This lead does not have a callable phone number. Please set Phone/Mobile on the lead or related customer.'),
                notification_type='danger',
                sticky=True,
            )

        log = self.create({
            'lead_id': lead.id,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
            'agent_email': agent_email,
            'phone_number': phone_number,
            'endpoint_url': config['endpoint_url'],
            'request_method': 'POST',
        })

        # Mandatory request body according to client document.
        payload = {
            'agent_email': agent_email,
            'value': phone_number,
            'calling_history_id': log.id,
        }

        log.sudo().write({
            'calling_history_id': log.id,
            'request_payload': json.dumps(payload, indent=2, ensure_ascii=False),
        })

        try:
            request_formats = [config['request_format']]
            if config['request_format'] == 'auto':
                # First follow client document exactly. If provider rejects method/format,
                # retry using form-urlencoded because many PHP APIs read $_POST only.
                request_formats = ['json', 'form']

            attempts = []
            final_response = None
            final_parsed = None
            final_headers = None
            final_format = None

            for index, request_format in enumerate(request_formats):
                response, parsed, headers = self._post_click_to_call(
                    config['endpoint_url'],
                    payload,
                    config['authorization'],
                    config['timeout'],
                    request_format,
                )
                attempts.append({
                    'attempt': index + 1,
                    'method': 'POST',
                    'format': request_format,
                    'url': response.url,
                    'redirects': getattr(response, 'wub_redirects', []),
                    'http_status': response.status_code,
                    'api_status': parsed.get('api_status'),
                    'response_code': parsed.get('response_code'),
                    'result_reason': parsed.get('result_reason'),
                })
                final_response = response
                final_parsed = parsed
                final_headers = headers
                final_format = request_format

                if parsed['is_success']:
                    break

                # Only retry in auto mode and only when the provider response indicates
                # method/content-type/body parsing issue. Do not retry auth/security errors.
                if (
                    config['request_format'] != 'auto'
                    or request_format == request_formats[-1]
                    or not self._is_method_or_format_error(response, parsed)
                ):
                    break

            data = final_parsed.get('data') or {}
            result_reason = final_parsed.get('result_reason')
            error_message = False
            if not final_parsed['is_success']:
                error_message = result_reason or _('External API call failed.')
                if final_response.status_code == 405:
                    error_message = _(
                        'HTTP 405 Method Not Allowed. The external server rejected POST for this URL, '
                        'or the request reached the wrong route/server. If JSON attempt failed, this module '
                        'also tried form-urlencoded in Auto mode.'
                    )

            log.sudo().write({
                'state': 'success' if final_parsed['is_success'] else 'error',
                'is_active_call': final_parsed['is_success'],
                'http_status': final_response.status_code,
                'api_status': final_parsed.get('api_status'),
                'response_code': final_parsed.get('response_code'),
                'code_reason': data.get('code_reason'),
                'result_reason': result_reason,
                'number': data.get('number'),
                'agent': data.get('agent'),
                'dial_extension': data.get('dial_extension'),
                'error_message': error_message,
                'request_format': final_format,
                'request_headers': json.dumps(self._safe_headers_for_log(final_headers), indent=2, ensure_ascii=False),
                'response_payload': final_parsed.get('response_payload'),
                'debug_message': json.dumps(attempts, indent=2, ensure_ascii=False),
            })

            if final_parsed['is_success']:
                return self._notification(
                    title=_('IP Call Sent'),
                    message=_('Call request sent successfully for %(number)s. Request format: %(format)s.') % {
                        'number': data.get('number') or phone_number,
                        'format': final_format,
                    },
                    notification_type='success',
                    sticky=False,
                    reload=True,
                )

            return self._notification(
                title=_('IP Call Failed'),
                message=_('%(reason)s Check IP Calling History for full request/response.') % {
                    'reason': error_message,
                },
                notification_type='danger',
                sticky=True,
            )

        except requests.exceptions.Timeout:
            message = _('Request timeout. The external API did not respond within %(timeout)s seconds.') % {
                'timeout': config['timeout'],
            }
            log.sudo().write({
                'state': 'error',
                'error_message': message,
            })
            _logger.exception('WUB IP Calling timeout for lead %s', lead.id)
            return self._notification(_('IP Call Timeout'), message, 'danger', True)

        except requests.exceptions.RequestException as exc:
            message = _('Could not connect to external API: %(error)s') % {'error': str(exc)}
            log.sudo().write({
                'state': 'error',
                'error_message': message,
            })
            _logger.exception('WUB IP Calling request exception for lead %s', lead.id)
            return self._notification(_('IP Call Connection Error'), message, 'danger', True)

        except Exception as exc:  # noqa: BLE001 - keep CRM button safe and logged
            message = _('Unexpected IP Calling error: %(error)s') % {'error': str(exc)}
            log.sudo().write({
                'state': 'error',
                'error_message': message,
            })
            _logger.exception('Unexpected WUB IP Calling error for lead %s', lead.id)
            return self._notification(_('IP Call Error'), message, 'danger', True)

    @api.model
    def _notification(
        self,
        title,
        message,
        notification_type='info',
        sticky=False,
        reload=False,
    ):
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': sticky,
            },
        }
        if reload:
            action['params']['next'] = {
                'type': 'ir.actions.client',
                'tag': 'soft_reload',
            }
        return action
