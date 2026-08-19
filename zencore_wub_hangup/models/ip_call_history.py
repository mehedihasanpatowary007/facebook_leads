# -*- coding: utf-8 -*-
import json
import logging
from urllib.parse import urljoin

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ZencoreWubIpCallHistory(models.Model):
    _inherit = 'zencore.wub.ip.call.history'

    operation_type = fields.Selection(
        selection_add=[('hangup', 'Call Hangup')],
        ondelete={'hangup': 'set default'},
    )
    related_call_id = fields.Many2one(
        'zencore.wub.ip.call.history',
        string='Related Call',
        readonly=True,
        index=True,
        ondelete='set null',
        help='The active click-to-call record ended by this hangup operation.',
    )

    @api.model
    def _get_api_config(self):
        config = super()._get_api_config()
        hangup_endpoint_path = (
            self.env['ir.config_parameter'].sudo().get_param(
                'zencore_wub_ipcalling.hangup_endpoint_path',
                '/wub/api/call_hangup.php',
            )
            or ''
        ).strip()
        config.update({
            'hangup_endpoint_path': hangup_endpoint_path,
            'hangup_endpoint_url': (
                urljoin(
                    config['base_url'].rstrip('/') + '/',
                    hangup_endpoint_path.lstrip('/'),
                )
                if config['enabled'] and config['base_url'] and hangup_endpoint_path
                else ''
            ),
        })
        return config

    @api.model
    def _release_orphaned_active_calls(self):
        """Deactivate legacy active calls whose CRM lead was deleted."""
        orphaned_calls = self.sudo().search([
            ('lead_id', '=', False),
            ('operation_type', '=', 'click_to_call'),
            ('state', '=', 'success'),
            ('is_active_call', '=', True),
        ])
        if orphaned_calls:
            orphaned_calls.write({'is_active_call': False})
            _logger.warning(
                'Released %s orphaned WUB IP call(s): %s.',
                len(orphaned_calls),
                orphaned_calls.ids,
            )
        return orphaned_calls

    @api.model
    def _get_active_call(self, user=None, lead=None):
        """Ignore and repair call locks left behind by deleted leads."""
        self._release_orphaned_active_calls()
        return super()._get_active_call(user=user, lead=lead)

    def action_release_stale_call(self):
        """Manually release Odoo's local lock without calling the hangup API."""
        self.ensure_one()
        if self.operation_type != 'click_to_call' or not self.is_active_call:
            return self._notification(
                title=_('Call Already Inactive'),
                message=_('This IP call is already inactive.'),
                notification_type='info',
                sticky=False,
                reload=True,
            )

        self.sudo().write({'is_active_call': False})
        _logger.warning(
            'User %s manually released stale WUB IP call %s.',
            self.env.user.id,
            self.id,
        )
        return self._notification(
            title=_('Stale Call Released'),
            message=_(
                'The Odoo active-call lock was cleared. This action did not send a hangup request '
                'to the external IP calling service.'
            ),
            notification_type='success',
            sticky=False,
            reload=True,
        )

    @api.model
    def send_call_hangup(self, lead):
        """Hang up the current agent's call and log the API exchange."""
        lead.ensure_one()

        config = self._get_api_config()
        if not config['enabled']:
            return self._notification(
                title=_('IP Calling Disabled'),
                message=_('WUB IP Calling is disabled in Settings.'),
                notification_type='warning',
                sticky=True,
            )

        if not config['base_url'] or not config['hangup_endpoint_path']:
            return self._notification(
                title=_('Missing Hangup API Configuration'),
                message=_(
                    'Please configure the WUB IP Calling Base URL and Hangup Endpoint Path in Settings.'
                ),
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

        active_call = self._get_active_call(user=self.env.user, lead=lead)
        if not active_call:
            other_active_call = self._get_active_call(user=self.env.user)
            if other_active_call:
                message = _(
                    'There is no active call for this lead. Your active call belongs to %(lead)s.'
                ) % {
                    'lead': other_active_call.lead_id.display_name or _('another lead'),
                }
            else:
                message = _('There is no active IP call to hang up.')
            return self._notification(
                title=_('No Active Call'),
                message=message,
                notification_type='warning',
                sticky=False,
                reload=True,
            )

        agent_email = (active_call.agent_email or '').strip()
        payload = {'agent_email': agent_email}
        headers = self._base_headers(config['authorization'], 'json')
        log = self.create({
            'operation_type': 'hangup',
            'related_call_id': active_call.id,
            'lead_id': active_call.lead_id.id,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
            'agent_email': agent_email,
            'phone_number': active_call.phone_number or False,
            'endpoint_url': config['hangup_endpoint_url'],
            'request_method': 'POST',
            'request_format': 'json',
            'request_headers': json.dumps(
                self._safe_headers_for_log(headers),
                indent=2,
                ensure_ascii=False,
            ),
            'request_payload': json.dumps(payload, indent=2, ensure_ascii=False),
        })

        try:
            response, parsed, headers = self._post_api_request(
                config['hangup_endpoint_url'],
                payload,
                config['authorization'],
                config['timeout'],
                'json',
            )
            error_message = False
            if not parsed['is_success']:
                error_message = parsed.get('result_reason') or _('Call hangup failed.')

            attempts = [{
                'attempt': 1,
                'method': 'POST',
                'format': 'json',
                'url': response.url,
                'redirects': getattr(response, 'wub_redirects', []),
                'http_status': response.status_code,
                'api_status': parsed.get('api_status'),
                'response_code': parsed.get('response_code'),
                'result_reason': parsed.get('result_reason'),
            }]
            log.sudo().write({
                'state': 'success' if parsed['is_success'] else 'error',
                'http_status': response.status_code,
                'api_status': parsed.get('api_status'),
                'response_code': parsed.get('response_code'),
                'result_reason': parsed.get('result_reason'),
                'error_message': error_message,
                'request_headers': json.dumps(
                    self._safe_headers_for_log(headers),
                    indent=2,
                    ensure_ascii=False,
                ),
                'response_payload': parsed.get('response_payload'),
                'debug_message': json.dumps(attempts, indent=2, ensure_ascii=False),
            })

            if parsed['is_success']:
                active_call.sudo().write({'is_active_call': False})
                return self._notification(
                    title=_('Call Hung Up'),
                    message=parsed.get('result_reason') or _('Hangup Successfully'),
                    notification_type='success',
                    sticky=False,
                    reload=True,
                )

            return self._notification(
                title=_('Call Hangup Failed'),
                message=_('%(reason)s Check IP Calling History for the full response.') % {
                    'reason': error_message,
                },
                notification_type='danger',
                sticky=True,
            )

        except requests.exceptions.Timeout:
            message = _(
                'Hangup request timed out. The external API did not respond within %(timeout)s seconds.'
            ) % {'timeout': config['timeout']}
            log.sudo().write({'state': 'error', 'error_message': message})
            _logger.exception('WUB call hangup timeout for lead %s', lead.id)
            return self._notification(_('Call Hangup Timeout'), message, 'danger', True)

        except requests.exceptions.RequestException as exc:
            message = _('Could not connect to the call hangup API: %(error)s') % {
                'error': str(exc),
            }
            log.sudo().write({'state': 'error', 'error_message': message})
            _logger.exception('WUB call hangup request exception for lead %s', lead.id)
            return self._notification(_('Call Hangup Connection Error'), message, 'danger', True)

        except Exception as exc:  # noqa: BLE001 - keep the CRM button safe and log the error
            message = _('Unexpected call hangup error: %(error)s') % {'error': str(exc)}
            log.sudo().write({'state': 'error', 'error_message': message})
            _logger.exception('Unexpected WUB call hangup error for lead %s', lead.id)
            return self._notification(_('Call Hangup Error'), message, 'danger', True)
