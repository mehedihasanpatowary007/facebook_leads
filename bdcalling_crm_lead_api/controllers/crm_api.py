import json
from odoo import http
from odoo.http import request

class CrmLeadApi(http.Controller):

    @http.route('/api/crm/lead', type='http', auth='public', methods=['POST'], csrf=False)
    def create_crm_lead(self, **post):

        try:
            payload = json.loads(request.httprequest.data.decode('utf-8')) \
                if request.httprequest.data else post

            name = payload.get('name')
            email = payload.get('email')
            phone = payload.get('phone')
            course_name = payload.get('course')
            specialization_name = payload.get('specialization')
            query = payload.get('query')
            source_name = payload.get('source')

            #condition
            if not name or not email:
                return self._error("Name and Email are required", 400)
            if not course_name:
                return self._error("Course is required", 400)
            # if not specialization_name:
            #     return self._error("Specialization is required", 400)

            # ----------------------------
            # Normalize phone number
            # ----------------------------
            phone = self._normalize_phone(phone)

            Partner = request.env['res.partner'].sudo()
            Lead = request.env['crm.lead'].sudo()
            Source = request.env['utm.source'].sudo()

            # Partner
            partner = Partner.search([
                '|',
                ('email', '=', email),
                ('phone', '=', phone)
            ], limit=1)

            if not partner:
                partner = Partner.create({
                    'name': name,
                    'email': email,
                    'phone': phone,
                })

            # Source
            source = False
            if source_name:
                source = Source.search([('name', 'ilike', source_name)], limit=1)
                if not source:
                    source = Source.create({'name': source_name})

            # Lead values
            lead_vals = {
                'name': name,
                'partner_id': partner.id,
                'email_from': email,
                'phone': phone,
                'query': query,
                'course_id': course_name,
                'specialization_id': specialization_name,
                'type': 'lead',
                'user_id': False,       
                'team_id': False,       
            }

            if source:
                lead_vals['source_id'] = source.id
            
            lead = Lead.with_context(
                default_user_id=False,
                default_team_id=False,
            ).create(lead_vals)

            lead.write({
                'user_id': False,
                'team_id': False,
            })

            return request.make_response(
                json.dumps({
                    "status": "success",
                    "lead_id": lead.id,
                    "partner_id": partner.id,
                    "course": course_name,
                    "specialization": specialization_name,
                    "source": source.name if source else None
                }),
                headers=[('Content-Type', 'application/json')],
                status=201
            )

        except Exception as e:
            return self._error(str(e), 500)

    # ----------------------------
    # Phone Normalization Function
    # ----------------------------
    def _normalize_phone(self, phone):
        if not phone:
            return False
        phone = phone.strip()
        # Remove all non-digit characters
        phone = ''.join(filter(str.isdigit, phone))
        # Remove leading 0 if exists
        if phone.startswith('0'):
            phone = phone[1:]
        # Add country code 880 if not present
        if not phone.startswith('880'):
            phone = '880' + phone
        # Return in standard format with +880
        return '+' + phone

    def _error(self, message, status):
        return request.make_response(
            json.dumps({
                "status": "error",
                "error": message
            }),
            headers=[('Content-Type', 'application/json')],
            status=status
        )

# import json
# from odoo import http
# from odoo.http import request

# class CrmLeadApi(http.Controller):

#     # ------------------------------------------------------------
#     # Helper methods for API Key Authentication
#     # ------------------------------------------------------------
#     def _cors_headers(self):
#         """Return CORS headers"""
#         return [
#             ('Content-Type', 'application/json'),
#             ('Access-Control-Allow-Origin', '*'),
#             ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS'),
#             ('Access-Control-Allow-Headers', 'api-key, Content-Type'),
#             ('Access-Control-Max-Age', '86400'),
#         ]

#     def auth_api_key(self, api_key):
#         """Authenticate using API key"""
#         if not api_key:
#             return None, request.make_response(
#                 json.dumps({
#                     "status": "error",
#                     "error": "API key is required"
#                 }),
#                 headers=self._cors_headers(),
#                 status=401
#             )
        
#         try:
#             # Odoo 19 এ API key authentication
#             user = request.env['res.users.apikeys']._check_credentials(
#                 scope='rpc', key=api_key
#             )
            
#             if not user:
#                 return None, request.make_response(
#                     json.dumps({
#                         "status": "error",
#                         "error": "Invalid API key"
#                     }),
#                     headers=self._cors_headers(),
#                     status=401
#                 )
            
#             # Set the authenticated user
#             request.update_env(user=user)
#             return user, None
            
#         except Exception as e:
#             return None, request.make_response(
#                 json.dumps({
#                     "status": "error", 
#                     "error": f"Authentication error: {str(e)}"
#                 }),
#                 headers=self._cors_headers(),
#                 status=500
#             )

#     # ------------------------------------------------------------
#     # Public Endpoint (Without API Key)
#     # ------------------------------------------------------------
#     @http.route('/api/crm/lead', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
#     def create_crm_lead_http(self, **post):
#         """Public HTTP endpoint - No authentication required"""
#         return self._create_lead_common(post)

#     # ------------------------------------------------------------
#     # Authenticated Endpoint (With API Key)
#     # ------------------------------------------------------------
#     @http.route('/api/crm/lead/auth', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
#     def create_crm_lead_authenticated(self, **post):
#         """Authenticated HTTP endpoint - API key required"""
        
#         # Handle CORS preflight request
#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())
        
#         # Authenticate using API key
#         api_key = request.httprequest.headers.get('api-key')
#         user, error = self.auth_api_key(api_key)
#         if error:
#             return error
        
#         # Create lead with authenticated user context
#         return self._create_lead_common(post, user_id=user.id)

#     # ------------------------------------------------------------
#     # Common Lead Creation Logic
#     # ------------------------------------------------------------
#     def _create_lead_common(self, post_data, user_id=None):
#         """Common logic for creating leads"""
#         try:
#             # Get JSON data from request
#             if request.httprequest.data:
#                 try:
#                     payload = json.loads(request.httprequest.data.decode('utf-8'))
#                 except:
#                     payload = post_data
#             else:
#                 payload = post_data

#             # Log the request
#             print(f"[CRM API] Lead creation request: {payload}")

#             # DATA VALIDATION
#             name = payload.get('name')
#             email = payload.get('email')
#             phone = payload.get('phone')
#             course = payload.get('course')
#             specialization = payload.get('specialization')
#             query = payload.get('query')

#             if not name or not email:
#                 return request.make_response(
#                     json.dumps({
#                         "status": "error",
#                         "error": "Name and Email are required"
#                     }),
#                     headers=self._cors_headers(),
#                     status=400
#                 )

#             # Use appropriate environment based on authentication
#             if user_id:
#                 # Authenticated user - use their environment
#                 Partner = request.env['res.partner'].with_user(user_id)
#                 Lead = request.env['crm.lead'].with_user(user_id)
#                 print(f"[CRM API] Using authenticated user: {user_id}")
#             else:
#                 # Public user - use sudo
#                 Partner = request.env['res.partner'].sudo()
#                 Lead = request.env['crm.lead'].sudo()
#                 print("[CRM API] Using public (sudo) access")

#             # FIND / CREATE PARTNER
#             partner = Partner.search([
#                 '|',
#                 ('email', '=', email),
#                 ('phone', '=', phone)
#             ], limit=1)

#             if not partner:
#                 partner = Partner.create({
#                     'name': name,
#                     'email': email,
#                     'phone': phone,
#                 })
#                 print(f"[CRM API] Created new partner: {partner.id}")

#             # CREATE LEAD
#             lead_vals = {
#                 'name': f"{name}",
#                 'partner_id': partner.id,
#                 'email_from': email,
#                 'phone': phone,
#                 'description': query or '',  # Use description instead of query
#             }
            
#             # Add custom fields if they exist
#             if 'course' in Lead._fields:
#                 lead_vals['course'] = course
#             if 'specialization' in Lead._fields:
#                 lead_vals['specialization'] = specialization
#             if 'query' in Lead._fields:
#                 lead_vals['query'] = query

#             lead = Lead.create(lead_vals)
#             print(f"[CRM API] Created lead: {lead.id}")

#             return request.make_response(
#                 json.dumps({
#                     "status": "success",
#                     "lead_id": lead.id,
#                     "partner_id": partner.id,
#                     "message": "Lead created successfully"
#                 }),
#                 headers=self._cors_headers(),
#                 status=201
#             )

#         except Exception as e:
#             print(f"[CRM API] Error: {str(e)}")
#             return request.make_response(
#                 json.dumps({
#                     "status": "error",
#                     "error": str(e)
#                 }),
#                 headers=self._cors_headers(),
#                 status=500
#             )

#     # ------------------------------------------------------------
#     # API Key Management Endpoints
#     # ------------------------------------------------------------
#     @http.route('/api/crm/generate-api-key', type='http', auth='user', methods=['GET'], csrf=False)
#     def generate_api_key(self, **kw):
#         """Generate a new API key for the current user"""
#         try:
#             user = request.env.user
#             api_key_obj = request.env['res.users.apikeys'].sudo()
            
#             # Create new API key
#             key = api_key_obj._generate('CRM API Key', user.id)
            
#             return request.make_response(
#                 json.dumps({
#                     "status": "success",
#                     "api_key": key,
#                     "user_id": user.id,
#                     "username": user.login,
#                     "message": "Store this API key securely. It will not be shown again."
#                 }),
#                 headers=self._cors_headers(),
#                 status=201
#             )
#         except Exception as e:
#             return request.make_response(
#                 json.dumps({
#                     "status": "error",
#                     "error": str(e)
#                 }),
#                 headers=self._cors_headers(),
#                 status=500
#             )

#     @http.route('/api/crm/test-auth', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
#     def test_auth(self, **kw):
#         """Test authentication endpoint"""
#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())
        
#         api_key = request.httprequest.headers.get('api-key')
#         user, error = self.auth_api_key(api_key)
        
#         if error:
#             return error
        
#         return request.make_response(
#             json.dumps({
#                 "status": "success",
#                 "message": "Authentication successful",
#                 "user_id": user.id,
#                 "username": user.login,
#                 "email": user.email
#             }),
#             headers=self._cors_headers()
#         )




# import json
# import logging
# from odoo import http
# from odoo.http import request

# _logger = logging.getLogger(__name__)


# class CrmLeadAPI(http.Controller):

#     # ============================================================
#     # PUBLIC API (No Authentication)
#     # ============================================================
#     @http.route(
#         '/api/crm/lead/create',
#         type='http',
#         auth='public',
#         methods=['POST', 'OPTIONS'],
#         csrf=False
#     )
#     def create_lead_http(self, **post):

#         # Handle CORS preflight
#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())

#         try:
#             # -----------------------------
#             # Parse JSON / form payload
#             # -----------------------------
#             payload = (
#                 json.loads(request.httprequest.data.decode('utf-8'))
#                 if request.httprequest.data else post
#             )

#             # -----------------------------
#             # Validation
#             # -----------------------------
#             name = payload.get('name')
#             email = payload.get('email')
#             phone = payload.get('phone')
#             course = payload.get('course')
#             specialization = payload.get('specialization')
#             query = payload.get('query')

#             if not name or not email:
#                 return self._error_response(
#                     "Name and Email are required", 400
#                 )

#             Partner = request.env['res.partner'].sudo()
#             Lead = request.env['crm.lead'].sudo()

#             # -----------------------------
#             # Find or create partner
#             # -----------------------------
#             partner = Partner.search([
#                 '|',
#                 ('email', '=', email),
#                 ('phone', '=', phone)
#             ], limit=1)

#             if not partner:
#                 partner = Partner.create({
#                     'name': name,
#                     'email': email,
#                     'phone': phone,
#                 })

#             # -----------------------------
#             # Create CRM Lead
#             # -----------------------------
#             lead_vals = {
#                 'name': name,
#                 'partner_id': partner.id,
#                 'email_from': email,
#                 'phone': phone,
#                 'query': query,
#                 'course': course,
#                 'specialization': specialization,
#             }

#             lead = Lead.create(lead_vals)

#             return self._success_response({
#                 'lead_id': lead.id,
#                 'partner_id': partner.id,
#                 'message': 'CRM Lead created successfully'
#             }, 201)

#         except Exception as e:
#             _logger.exception("Public Lead API error")
#             return self._error_response(str(e), 500)

#     # ============================================================
#     # AUTHENTICATED API (API KEY)
#     # ============================================================
#     @http.route('/api/crm/lead/create/auth', type='http', auth='public',
#                 methods=['POST', 'OPTIONS'], csrf=False)
#     def create_lead_authenticated(self, **post):

#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())

#         try:
#             # -------------------------------------------------
#             # API KEY VALIDATION
#             # -------------------------------------------------
#             api_key = request.httprequest.headers.get('api-key')
#             if api_key != '7631c844ef705ff553a624790281188fe6883a79':
#                 return self._error_response("Invalid API key", 401)

#             # -------------------------------------------------
#             # Parse payload
#             # -------------------------------------------------
#             payload = json.loads(request.httprequest.data.decode('utf-8')) \
#                 if request.httprequest.data else post

#             name = payload.get('name')
#             email = payload.get('email')
#             phone = payload.get('phone')
#             course = payload.get('course')
#             specialization = payload.get('specialization')
#             query = payload.get('query')

#             if not name or not email:
#                 return self._error_response("Name and Email are required", 400)

#             # -------------------------------------------------
#             # SUDO ENV (SAFE)
#             # -------------------------------------------------
#             Partner = request.env['res.partner'].sudo()
#             Lead = request.env['crm.lead'].sudo()

#             partner = Partner.search([
#                 '|', ('email', '=', email), ('phone', '=', phone)
#             ], limit=1)

#             if not partner:
#                 partner = Partner.create({
#                     'name': name,
#                     'email': email,
#                     'phone': phone,
#                 })

#             lead_vals = {
#                 'name': name,
#                 'partner_id': partner.id,
#                 'email_from': email,
#                 'phone': phone,
#                 'company_id': request.env.company.id,
#             }

#             if course and 'course' in Lead._fields:
#                 lead_vals['course'] = course

#             if specialization and 'specialization' in Lead._fields:
#                 lead_vals['specialization'] = specialization

#             if query and 'query' in Lead._fields:
#                 lead_vals['query'] = query

#             lead = Lead.create(lead_vals)

#             return self._success_response({
#                 'lead_id': lead.id,
#                 'partner_id': partner.id,
#                 'message': 'Authenticated CRM Lead created successfully'
#             }, 201)

#         except Exception as e:
#             _logger.exception("Authenticated Lead API error")
#             return self._error_response(str(e), 500)


#     # ============================================================
#     # Helper Methods (Controller internal)
#     # ============================================================
#     def _success_response(self, data, status=200):
#         return request.make_response(
#             json.dumps({
#                 'status': 'success',
#                 'data': data
#             }),
#             headers=[('Content-Type', 'application/json')],
#             status=status
#         )

#     def _error_response(self, message, status=400):
#         return request.make_response(
#             json.dumps({
#                 'status': 'error',
#                 'message': message
#             }),
#             headers=[('Content-Type', 'application/json')],
#             status=status
#         )

#     def _cors_headers(self):
#         return [
#             ('Access-Control-Allow-Origin', '*'),
#             ('Access-Control-Allow-Headers', 'Content-Type, api-key'),
#             ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
#         ]





# import json
# import logging
# from odoo import http
# from odoo.http import request

# _logger = logging.getLogger(__name__)


# class CrmLeadAPI(http.Controller):

#     # =====================================================
#     # PUBLIC API (no api key)
#     # =====================================================
#     @http.route([
#         '/api/crm/lead',
#         '/odoo/api/crm/lead'
#     ], type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
#     def create_lead_public(self, **post):

#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())

#         return self._create_lead(post, authenticated=False)

#     # =====================================================
#     # AUTHENTICATED API (API KEY)
#     # =====================================================
#     @http.route([
#         '/api/crm/lead/auth',
#         '/odoo/api/crm/lead/auth'
#     ], type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
#     def create_lead_authenticated(self, **post):

#         if request.httprequest.method == 'OPTIONS':
#             return request.make_response('', headers=self._cors_headers())

#         # ----------------------------
#         # API KEY VALIDATION
#         # ----------------------------
#         api_key = request.httprequest.headers.get('api-key')
#         if not self._is_valid_api_key(api_key):
#             return self._error_response("Invalid API key", 401)

#         return self._create_lead(post, authenticated=True)

#     # =====================================================
#     # CORE LOGIC (shared)
#     # =====================================================
#     def _create_lead(self, post, authenticated=False):

#         try:
#             payload = json.loads(request.httprequest.data.decode('utf-8')) \
#                 if request.httprequest.data else post

#             name = payload.get('name')
#             email = payload.get('email')
#             phone = payload.get('phone')
#             course = payload.get('course')
#             specialization = payload.get('specialization')
#             query = payload.get('query')

#             if not name or not email:
#                 return self._error_response("Name and Email are required", 400)

#             Partner = request.env['res.partner'].sudo()
#             Lead = request.env['crm.lead'].sudo()

#             partner = Partner.search([
#                 '|', ('email', '=', email), ('phone', '=', phone)
#             ], limit=1)

#             if not partner:
#                 partner = Partner.create({
#                     'name': name,
#                     'email': email,
#                     'phone': phone,
#                 })

#             lead_vals = {
#                 'name': name,
#                 'partner_id': partner.id,
#                 'email_from': email,
#                 'phone': phone,
#                 'company_id': request.env.company.id,
#             }

#             if course and 'course' in Lead._fields:
#                 lead_vals['course'] = course

#             if specialization and 'specialization' in Lead._fields:
#                 lead_vals['specialization'] = specialization

#             if query and 'query' in Lead._fields:
#                 lead_vals['query'] = query

#             lead = Lead.create(lead_vals)

#             return self._success_response({
#                 'lead_id': lead.id,
#                 'partner_id': partner.id,
#                 'authenticated': authenticated,
#                 'message': 'CRM Lead created successfully'
#             }, 201)

#         except Exception as e:
#             _logger.exception("CRM Lead API error")
#             return self._error_response(str(e), 500)

#     # =====================================================
#     # API KEY CHECK (DB BASED)
#     # =====================================================
#     def _is_valid_api_key(self, api_key):
#         if not api_key:
#             return False

#         keys = request.env['ir.config_parameter'].sudo().get_param(
#             'crm_api_keys', ''
#         )

#         allowed_keys = [k.strip() for k in keys.split(',') if k.strip()]
#         return api_key in allowed_keys

#     # =====================================================
#     # HELPERS
#     # =====================================================
#     def _success_response(self, data, status=200):
#         return request.make_response(
#             json.dumps({'status': 'success', 'data': data}),
#             headers=[('Content-Type', 'application/json')],
#             status=status
#         )

#     def _error_response(self, message, status=400):
#         return request.make_response(
#             json.dumps({'status': 'error', 'message': message}),
#             headers=[('Content-Type', 'application/json')],
#             status=status
#         )

#     def _cors_headers(self):
#         return [
#             ('Access-Control-Allow-Origin', '*'),
#             ('Access-Control-Allow-Headers', 'Content-Type, api-key, X-Odoo-Database'),
#             ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
#         ]
