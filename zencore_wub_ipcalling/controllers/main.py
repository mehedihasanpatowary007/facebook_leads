from odoo import http, fields
from odoo.http import request
import json
from datetime import datetime, timezone
from markupsafe import Markup

class WubIPCallingController(http.Controller):

    def _json_payload(self):
        try:
            return json.loads(request.httprequest.data or b"{}")
        except ValueError:
            return {}

    def _authorization_ok(self):
        """Optional inbound security for dialer callbacks.

        If system parameter wub_ip_calling.inbound_authorization_key is empty,
        inbound callbacks are accepted. If configured, caller must send the same
        Authorization header.
        """
        expected = request.env["ir.config_parameter"].sudo().get_param(
            "wub_ip_calling.inbound_authorization_key"
        )
        if not expected:
            return True
        return request.httprequest.headers.get("Authorization") == expected

    def _records_from_payload(self, payload):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return [payload]

    def _partner_phone_domain(self, Partner, phone):
        phone_fields = [
            field_name
            for field_name in ("phone", "mobile", "phone_sanitized")
            if field_name in Partner._fields
        ]
        if not phone_fields:
            return False
        return fields.Domain.OR(fields.Domain(field_name, "=", phone) for field_name in phone_fields)

    def _partner_create_values(self, Partner, phone):
        values = {"name": phone}
        if "phone" in Partner._fields:
            values["phone"] = phone
        elif "mobile" in Partner._fields:
            values["mobile"] = phone
        return values

    @http.route('/api/ip_calling/lead', type='http', auth='public', methods=['POST'], csrf=False)
    def create_lead(self, **kwargs):
        if not self._authorization_ok():
            return request.make_json_response({
                'success': False,
                'message': 'Unauthorized',
            }, status=401)

        try:
            data = self._json_payload()
            phone = data.get('phone') or data.get('phone_number') or data.get('value')

            if not phone:
                return request.make_json_response({
                    'success': False,
                    'message': 'Phone number is required'
                }, status=400)

            Partner = request.env['res.partner'].sudo()
            contact_domain = self._partner_phone_domain(Partner, phone)
            contact = Partner.search(contact_domain, limit=1) if contact_domain else Partner.browse()
            if not contact:
                contact = Partner.create(self._partner_create_values(Partner, phone))

            source = request.env['utm.source'].sudo().search(
                [('name', '=', 'Missed Call')],
                limit=1
            )
            if not source:
                source = request.env['utm.source'].sudo().create({'name': 'Missed Call'})

            lead = request.env['crm.lead'].sudo().create({
                'name': data.get('name') or phone,
                'phone': phone,
                'type': 'lead',
                'partner_id': contact.id,
                'source_id': source.id,
                'user_id': False,
                'team_id': False,
            })

            return request.make_json_response({
                'success': True,
                'lead_id': lead.id,
                'lead_name': lead.name,
                'phone': lead.phone,
                'created_at': fields.Datetime.to_string(lead.create_date),
                'message': 'Lead created successfully'
            }, status=200)

        except Exception as e:
            return request.make_json_response({
                'success': False,
                'message': str(e)
            }, status=500)

    @http.route(
        ['/api/ip_calling/call_log', '/api/ip_calling/outbound_data', '/api/ip_calling/drop_call_data'],
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def create_or_update_call_log(self, **kwargs):
        """Receive call result callback from dialer.

        Supports the client supplied formats:
        1) Outbound Data: {"status":"200", "data": [{"calling_history_id": 2, ...}]}
        2) Drop Call Data: {"status":"200", "data": [{"status":"DROP", ...}]}
        Also remains backward compatible with the previous single call_log payload.
        """
        if not self._authorization_ok():
            return request.make_json_response({
                'success': False,
                'message': 'Unauthorized',
            }, status=401)

        payload = self._json_payload()
        records = self._records_from_payload(payload)
        processed = []
        errors = []

        for item in records:
            try:
                result = self._process_dialer_record(item, payload)
                processed.append(result)
            except Exception as error:
                errors.append(str(error))

        status_code = 200 if not errors else 207
        return request.make_json_response({
            "success": not bool(errors),
            "processed": processed,
            "errors": errors,
        }, status=status_code)

    def _process_dialer_record(self, item, full_payload):
        History = request.env['zencore.wub.ip.call.history'].sudo()

        calling_history_id = item.get('calling_history_id') or item.get('callingHistoryId')
        phone_number = item.get('phone_number') or item.get('customer_number') or item.get('value')
        call_time = item.get('call_time') or item.get('call_start_time')
        dialer_status = item.get('status')

        history = History.browse()
        if calling_history_id:
            try:
                history = History.browse(int(calling_history_id)).exists()
            except (TypeError, ValueError):
                history = History.browse()

        # Drop call example does not include calling_history_id. In that case, match latest history by phone.
        if not history and phone_number:
            history = History.search([
                ('phone_number', '=', phone_number),
                ('operation_type', '=', 'click_to_call'),
            ], order='id desc', limit=1)

        lead = history.lead_id if history else request.env['crm.lead'].sudo().browse()
        call_id = item.get('call_id') or self._build_call_id(calling_history_id, phone_number, call_time, dialer_status)

        values = {
            'callback_received_at': fields.Datetime.now(),
            'call_id': call_id,
            'call_time': self._parse_datetime(call_time),
            'dialer_status': dialer_status,
            'call_status': item.get('call_status'),
            'agent_id': item.get('agent_id'),
            'agent_full_name': item.get('agent_full_name'),
            'campaign': item.get('campaign'),
            'length_in_sec': self._safe_int(item.get('length_in_sec')),
            # Client document has typo: term_reson. Support both spellings.
            'term_reason': item.get('term_reason') or item.get('term_reson'),
            'recording_url': item.get('recording_url') or item.get('Recording_url'),
            'queue_seconds': self._safe_int(item.get('queue_seconds')),
            'callback_payload': json.dumps(full_payload, indent=4, ensure_ascii=False),
        }
        values = {key: value for key, value in values.items() if value not in (None, False)}
        if history and self._is_terminal_dialer_record(item):
            values['is_active_call'] = False

        if history:
            history.write(values)

        if lead:
            self._post_call_result_to_chatter(lead, history, item)

        return {
            'calling_history_id': history.id if history else False,
            'call_id': call_id,
            'phone_number': phone_number,
            'status': dialer_status,
            'matched_history': bool(history),
            'lead_id': lead.id if lead else False,
        }

    def _is_terminal_dialer_record(self, item):
        """Identify callbacks that prove the call is no longer running.

        Connected/ringing callbacks must leave the call active. A callback with
        duration, termination reason, or recording data is a final result even
        when the provider reports its status as ANSWER.
        """
        result_fields = (
            'length_in_sec',
            'term_reason',
            'term_reson',
            'recording_url',
            'Recording_url',
        )
        if any(item.get(field_name) not in (None, False, '') for field_name in result_fields):
            return True

        terminal_statuses = {
            'busy',
            'cancelled',
            'canceled',
            'complete',
            'completed',
            'disconnected',
            'drop',
            'ended',
            'failed',
            'hangup',
            'hungup',
            'no answer',
            'no_answer',
            'terminated',
        }
        statuses = {
            str(item.get('status') or '').strip().lower(),
            str(item.get('call_status') or '').strip().lower(),
        }
        return bool(statuses & terminal_statuses)

    def _post_call_result_to_chatter(self, lead, history, item):
        recording_url = item.get('recording_url') or item.get('Recording_url') or '#'
        length = self._safe_int(item.get('length_in_sec')) or (history.length_in_sec if history else 0) or 0
        message = Markup(f"""
            <p><strong>IP Calling Result</strong></p>
            <ul>
                <li><strong>Status:</strong> {item.get('status') or (history.dialer_status if history else '-') or '-'}</li>
                <li><strong>Call Status:</strong> {item.get('call_status') or (history.call_status if history else '-') or '-'}</li>
                <li><strong>Agent:</strong> {item.get('agent_full_name') or item.get('agent_id') or (history.agent_full_name if history else '-') or '-'}</li>
                <li><strong>Campaign:</strong> {item.get('campaign') or (history.campaign if history else '-') or '-'}</li>
                <li><strong>Call Time:</strong> {item.get('call_time') or item.get('call_start_time') or (history.call_time if history else '-') or '-'}</li>
                <li><strong>Length:</strong> {length} sec</li>
                <li><strong>Term Reason:</strong> {item.get('term_reason') or item.get('term_reson') or (history.term_reason if history else '-') or '-'}</li>
            </ul>
            <p><strong>Recording:</strong> <a href="{recording_url}" target="_blank">Open Recording</a></p>
        """)
        lead.message_post(body=message, subtype_xmlid="mail.mt_note")

    def _safe_int(self, value):
        if value in (None, False, ''):
            return False
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return False

    def _parse_datetime(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            try:
                return fields.Datetime.to_datetime(text)
            except Exception:
                try:
                    dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
                except Exception:
                    try:
                        dt = datetime.strptime(text, '%Y-%m-%dT%H:%M:%S%z')
                    except Exception:
                        return False
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _map_call_status(self, value):
        value = (value or '').lower()
        if value in ('answer', 'answered', 'xfer'):
            return 'answered'
        if value in ('no_answer', 'no answer', 'na'):
            return 'no_answer'
        if value == 'busy':
            return 'busy'
        if value in ('cancelled', 'canceled', 'drop'):
            return 'cancelled'
        if value:
            return 'failed'
        return False

    def _build_call_id(self, calling_history_id, phone_number, call_time, status):
        parts = [
            str(calling_history_id or 'no-history'),
            str(phone_number or 'no-phone'),
            str(call_time or fields.Datetime.now()),
            str(status or 'no-status'),
        ]
        return '|'.join(parts)
