# -*- coding: utf-8 -*-
import json
import logging
import base64
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class HelpdeskApi(http.Controller):

    # ------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------
    def _cors_headers(self):
        return [
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'api-key, Content-Type'),
        ]

    def _error_response(self, message, status=400):
        return request.make_response(
            json.dumps({'status': 'error', 'error': message, 'code': status}),
            headers=self._cors_headers(),
            status=status
        )

    def _success_response(self, data, status=200):
        payload = {'status': 'success'}
        payload.update(data)
        return request.make_response(
            json.dumps(payload),
            headers=self._cors_headers(),
            status=status
        )

    # ------------------------------------------------------------
    # API Key Authentication - FIXED
    # ------------------------------------------------------------
    def auth_api_key(self, api_key):
        """Authenticate using API key and return user_id"""
        if not api_key:
            return None, self._error_response('No API Key Provided', 401)

        try:
            # Correct way to check API key in Odoo 19
            user_id = request.env['res.users.apikeys'].sudo()._check_credentials(
                scope='rpc', 
                key=api_key
            )
            
            if not user_id:
                return None, self._error_response('Invalid API Key', 401)

            return user_id, None

        except Exception as e:
            _logger.error(f"API Key authentication error: {e}", exc_info=True)
            return None, self._error_response('Authentication failed', 401)

    # ------------------------------------------------------------
    # Validation & Core Logic
    # ------------------------------------------------------------
    def validate_ticket_data(self, data):
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()

        if not name:
            return None, self._error_response('Name is required', 400)

        if not email:
            return None, self._error_response('Email is required', 400)

        if '@' not in email:
            return None, self._error_response('Invalid email format', 400)

        help_topic = (
            data.get('help_topic')
            or data.get('helpTopic')
            or data.get('help-topic')
            or data.get('Help Topic')
            or ''
        )

        return {
            'name': name,
            'email': email,
            'phone': (data.get('phone') or '').strip(),
            'issue': (data.get('issue') or '').strip(),
            'description': (data.get('description') or '').strip(),
            'help_topic': str(help_topic).strip(),
        }, None

    def find_or_create_partner(self, name, email, phone, user_id=None):
        """Find or create partner with proper environment"""
        try:
            env = request.env
            if user_id:
                env = env(user=user_id)
            
            Partner = env['res.partner'].sudo()

            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                if phone and partner.phone != phone:
                    partner.write({'phone': phone})
                return partner, None

            partner = Partner.create({
                'name': name,
                'email': email,
                'phone': phone or False,
            })
            return partner, None

        except Exception as e:
            _logger.error(f"Partner error: {e}", exc_info=True)
            return None, self._error_response(str(e), 500)

    def create_helpdesk_ticket(self, partner, issue, description, team_id=None, user_id=None, help_topic=None, env_user_id=None):
        """Create helpdesk ticket - FIXED to remove hardcoded values"""
        try:
            env = request.env
            if env_user_id:
                env = env(user=env_user_id)
            
            Ticket = env['helpdesk.ticket'].sudo()

            # Get default team if not provided
            # if not team_id:
            #     team = env['helpdesk.team'].sudo().search([('name', '=', 'WUB')], limit=1)
            #     if team:
            #         team_id = team.id
            #     else:
            #         team = env['helpdesk.team'].sudo().create({
            #             'name': "WUB"
            #         })
            #         team_id = team.id
            # if not user_id:
            #     users = env['res.users'].sudo().search([], limit=1)
            #     if users:
            #         user_id = users.id
            #     else:
            #         users = env['res.users'].sudo().create({
            #             'name': "admin",
            #             'email': 'admin@gmail.com'
            #         })
            #         user_id = users.id

            vals = {
                'name': issue or f"Support Request from {partner.name}",
                'partner_id': partner.id,
                'description': description or '',
                # 'user_id':,
                'team_id':False,
                'email_cc': '',
                'help_topic': help_topic or '',

            }

            ticket = Ticket.create(vals)
            return ticket, None

        except Exception as e:
            _logger.error(f"Ticket creation error: {e}", exc_info=True)
            return None, self._error_response(str(e), 500)

    # ------------------------------------------------------------
    # File Upload Handlers
    # ------------------------------------------------------------
    def handle_file_upload(self, ticket, user_id=None):
        """Handle file upload with proper environment"""
        try:
            upload = request.httprequest.files.get('file')
            if not upload:
                return None, None

            file_content = upload.read()
            if len(file_content) > 10 * 1024 * 1024:
                return None, self._error_response('File exceeds 10MB limit', 400)

            env = request.env
            if user_id:
                env = env(user=user_id)

            attachment = env['ir.attachment'].sudo().create({
                'name': upload.filename,
                'type': 'binary',
                'datas': base64.b64encode(file_content),
                'mimetype': upload.mimetype,
                'res_model': 'helpdesk.ticket',
                'res_id': ticket.id,
            })

            ticket.sudo().message_post(
                body="File attached",
                attachment_ids=[attachment.id]
            )

            return attachment, None

        except Exception as e:
            _logger.error(f"File upload error: {e}", exc_info=True)
            return None, {'warning': str(e)}

    # ------------------------------------------------------------
    # HTTP Endpoint (Multipart / Form-Data) - PUBLIC
    # ------------------------------------------------------------
    @http.route('/api/helpdesk/ticket/create', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, save_session=False)
    def create_ticket_http(self, **post):
        """Public endpoint for ticket creation"""
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self._cors_headers())

        try:
            super_user_id = 1
            # Parse payload from JSON or form data
            if request.httprequest.data:
                try:
                    payload = json.loads(request.httprequest.data.decode('utf-8'))
                except Exception:
                    payload = post
            else:
                payload = post

            validated, error = self.validate_ticket_data(payload)
            if error:
                return error
            partner, error = self.find_or_create_partner(
                validated['name'], 
                validated['email'], 
                validated['phone'],
                user_id = super_user_id
            )
            if error:
                return error

            ticket, error = self.create_helpdesk_ticket(
                partner,
                validated['issue'],
                validated['description'],
                payload.get('team_id'),
                payload.get('user_id'),
                help_topic=validated['help_topic'],
                env_user_id=super_user_id
            )
            if error:
                return error
            
            attachment, file_error = self.handle_file_upload(ticket, user_id=super_user_id)

            response = {
                'ticket_id': ticket.id,
                'ticket_name': ticket.name,
                'help_topic': ticket.help_topic or '',
                'partner_id': partner.id,
                'partner_name': partner.name,
                'message': 'Ticket created successfully'
            }

            if attachment:
                response.update({
                    'attachment_id': attachment.id,
                    'attachment_name': attachment.name
                })

            if isinstance(file_error, dict):
                response['warning'] = file_error.get('warning')

            return self._success_response(response, 201)

        except Exception as e:
            _logger.error(f"HTTP API error: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    # # ------------------------------------------------------------
    # # Authenticated API Key Endpoint - FIXED
    # # ------------------------------------------------------------
    # @http.route('/api/helpdesk/ticket/create/auth', type='http', auth='none',
    #             methods=['POST', 'OPTIONS'], csrf=False, save_session=False)
    # def create_ticket_authenticated(self, **post):
    #     """Authenticated endpoint using API key"""
    #     if request.httprequest.method == 'OPTIONS':
    #         return request.make_response('', headers=self._cors_headers())

    #     try:
    #         # Get and validate API key
    #         api_key = request.httprequest.headers.get('api-key')
    #         user_id, error = self.auth_api_key(api_key)
    #         if error:
    #             return error

    #         # Parse payload
    #         if request.httprequest.data:
    #             try:
    #                 payload = json.loads(request.httprequest.data.decode('utf-8'))
    #             except Exception:
    #                 payload = post
    #         else:
    #             payload = post

    #         validated, error = self.validate_ticket_data(payload)
    #         if error:
    #             return error

    #         # Create partner with authenticated user context
    #         partner, error = self.find_or_create_partner(
    #             validated['name'], 
    #             validated['email'], 
    #             validated['phone'],
    #             user_id=user_id
    #         )
    #         if error:
    #             return error

    #         # Create ticket with authenticated user context
    #         ticket, error = self.create_helpdesk_ticket(
    #             partner,
    #             validated['issue'],
    #             validated['description'],
    #             payload.get('team_id'),
    #             payload.get('user_id'),
    #             env_user_id=user_id
    #         )
    #         if error:
    #             return error

    #         # Handle file upload
    #         attachment, file_error = self.handle_file_upload(ticket, user_id=user_id)

    #         response = {
    #             'ticket_id': ticket.id,
    #             'ticket_name': ticket.name,
    #             'partner_id': partner.id,
    #             'partner_name': partner.name,
    #             'message': 'Ticket created successfully'
    #         }

    #         if attachment:
    #             response.update({
    #                 'attachment_id': attachment.id,
    #                 'attachment_name': attachment.name
    #             })

    #         if isinstance(file_error, dict):
    #             response['warning'] = file_error.get('warning')

    #         return self._success_response(response, 201)

    #     except Exception as e:
    #         _logger.error(f"Authenticated API error: {e}", exc_info=True)
    #         return self._error_response(str(e), 500)
