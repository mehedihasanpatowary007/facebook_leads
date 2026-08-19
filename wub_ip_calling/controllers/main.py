from odoo import http
from odoo.http import request
import json
from markupsafe import Markup

class WubIPCallingController(http.Controller):

    @http.route('/api/ip_calling/lead', type='http', auth='public', methods=['POST'], csrf=False )
    def create_lead(self, **kwargs):
        try:
            data = json.loads(request.httprequest.data)

            phone = data.get('phone')

            if not phone:
                return request.make_json_response({
                    'success': False,
                    'message': 'Phone number is required'
                }, status=400)

            contact = request.env['res.partner'].sudo().search(
                [('phone','=', phone)],
                limit=1
            )
            if not contact:
                contact = request.env['res.partner'].sudo().create({
                    'name': phone,
                    'phone': phone
                })

            source = request.env['utm.source'].sudo().search(
                [('name', '=', 'Missed Call')],
                limit=1
            )

            if not source:
                source = request.env['utm.source'].sudo().create({
                    'name': 'Missed Call',
                })

            lead = request.env['crm.lead'].sudo().create({
                'name': phone,
                'phone': phone,
                'type': 'lead',
                'partner_id': contact.id,
                'source_id': source.id,
                'user_id': '',
                'team_id': '',
            })

            return request.make_json_response({
                'success': True,
                'lead_id': lead.id,
                'lead_name': lead.name,
                'phone': lead.phone,
                'created_at': lead.create_date.strftime('%Y-%m-%d %H:%M:%S'),
                'message': 'Lead created successfully'
            }, status=200)

        except Exception as e:
            return request.make_json_response({
                'success': False,
                'message': str(e)
            }, status=500)
        
    @http.route(
        '/api/ip_calling/call_log',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def create_call_log(self, **kwargs):
        data = json.loads(request.httprequest.data)
        call_id = data.get("call_id")
        lead_id = data.get("lead_id")

        existing_log = request.env[
            'wub.call.log'
        ].sudo().search(
            [('call_id', '=', call_id)],
            limit=1
        )

        if existing_log:
            return request.make_json_response({
                "success": False,
                "message": "Call log already exists."
            }, status=400)
        

        lead = request.env[
            'crm.lead'
        ].sudo().browse(lead_id)

        if not lead.exists():
            return request.make_json_response({
                "success": False,
                "message": "Lead not found."
            }, status=404)
        

        call_log = request.env[
            'wub.call.log'
        ].sudo().create({
            'call_id': call_id,
            'lead_id': lead.id,
            'direction': data.get('direction'),
            'caller_user': data.get('caller_user'),
            'caller_extension': data.get('caller_extension'),
            'customer_number': data.get('customer_number'),
            'call_start_time': data.get('call_start_time'),
            'call_answer_time': data.get('call_answer_time'),
            'call_end_time': data.get('call_end_time'),
            'ring_duration': data.get('ring_duration'),
            'talk_duration': data.get('talk_duration'),
            'total_duration': data.get('total_duration'),
            'call_status': data.get('call_status'),
            'recording_url': data.get('recording_url'),
            'remarks': data.get('remarks'),
        })

        talk_duration = call_log.talk_duration or 0
        total_duration = call_log.total_duration or 0

        talk_duration_display = (
            f"{talk_duration // 3600:02d}:"
            f"{(talk_duration % 3600) // 60:02d}:"
            f"{talk_duration % 60:02d}"
        )

        total_duration_display = (
            f"{total_duration // 3600:02d}:"
            f"{(total_duration % 3600) // 60:02d}:"
            f"{total_duration % 60:02d}"
        )

        # create chatter
        message = Markup(f"""
        <p><strong>📞 Outgoing Call Log</strong></p>

        <ul>
            <li><strong>Status:</strong> {call_log.call_status or '-'}</li>
            <li><strong>Caller User:</strong> {call_log.caller_user or '-'}</li>
            <li><strong>Start Time:</strong> {call_log.call_start_time or '-'}</li>
            <li><strong>End Time:</strong> {call_log.call_end_time or '-'}</li>
            <li><strong>Talk Duration:</strong> {talk_duration_display}</li>
            <li><strong>Total Duration:</strong> {total_duration_display}</li>
        </ul>

        <p>
            <strong>Recording:</strong>
            <a href="{call_log.recording_url or '#'}" target="_blank">
                Open Recording
            </a>
        </p>
        """)
        lead.message_post(
            body=message,
            subtype_xmlid="mail.mt_note",
        )

        return request.make_json_response({
            "success": True,
            "call_log_id": call_log.id,
            "message": "Call log created successfully."
        }, status=200)
