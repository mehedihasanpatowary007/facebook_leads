# -*- coding: utf-8 -*-
"""
Shared helpers for the Helpdesk Student REST API.

Responsibilities
----------------
- Bearer / API-key authentication decorator
- Partner resolution from student e-mail
- Uniform JSON response builders  (success / error)
- Ticket serialisers              (list item vs. full detail)
- Tokenised attachment download URL generation
"""

import json
import logging
from email.utils import parseaddr
from functools import wraps
from urllib.parse import urlencode

from odoo.exceptions import AccessError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------

def _current_database_name(env=None):
    """
    Return the current Odoo database name for this request.

    In multi-database deployments, external clients often call the API with
    ``X-Odoo-Database``. A plain browser download link cannot send that header,
    so generated download URLs also carry ``db=<database_name>``.
    """
    try:
        env = env or request.env
        return env.cr.dbname
    except Exception:
        return None


def _attachment_download_headers(env=None):
    """
    Header metadata for API clients that download with fetch/axios/Postman.

    Note: a normal HTML/browser link cannot send custom request headers.
    The generated URL therefore also contains the db query parameter.
    """
    db_name = _current_database_name(env)
    if not db_name:
        return {}
    return {
        'X-Odoo-Database': db_name,
    }


def _build_query_string(values):
    """Build a clean query string, ignoring empty values."""
    clean_values = {
        key: value
        for key, value in values.items()
        if value not in (None, False, '')
    }
    return urlencode(clean_values)


def _attachment_download_url(att_id, token=None, db_name=None):
    """
    Build browser-friendly downloadable attachment URL.

    Do NOT return /web/content directly in the public API because a browser
    click cannot attach ``X-Odoo-Database``. This route contains db=<dbname>
    and then streams the file after token validation.
    """
    db_name = db_name or _current_database_name()
    query = _build_query_string({
        'access_token': token,
        'download': 'true',
        'db': db_name,
    })
    return '/api/v1/helpdesk/attachments/%s/download?%s' % (att_id, query)


def _ensure_attachment_access_tokens(env, attachment_ids):
    """
    Ensure ir.attachment records have access_token.

    Returns:
        {attachment_id: access_token}
    """
    if not attachment_ids:
        return {}

    attachments = env['ir.attachment'].sudo().browse(attachment_ids).exists()

    token_map = {
        att.id: att.access_token
        for att in attachments
        if att.access_token
    }

    missing_attachments = attachments.filtered(lambda att: not att.access_token)

    if missing_attachments:
        try:
            tokens = missing_attachments.generate_access_token()
            token_map.update(dict(zip(missing_attachments.ids, tokens)))

            _logger.debug(
                "[Zencore] Generated access tokens for %d attachment(s).",
                len(missing_attachments),
            )
        except Exception as exc:
            _logger.error(
                "[Zencore] Failed to generate access tokens for attachments %s: %s",
                missing_attachments.ids,
                exc,
            )

    return token_map


def _prefetch_message_attachments(cr, env, message_ids):
    """
    Fetch all attachment metadata for message IDs in one SQL query,
    then ensure every attachment has an access token.

    Returns:
        {
            message_id: [
                {
                    id,
                    name,
                    mimetype,
                    url,
                    headers,
                },
                ...
            ]
        }
    """
    if not message_ids:
        return {}

    cr.execute("""
        SELECT
            mar.message_id,
            ia.id           AS att_id,
            ia.name         AS att_name,
            ia.mimetype     AS att_mimetype,
            ia.access_token AS att_token
        FROM message_attachment_rel mar
        JOIN ir_attachment ia ON ia.id = mar.attachment_id
        WHERE mar.message_id = ANY(%s)
        ORDER BY mar.message_id, ia.id
    """, (list(message_ids),))

    rows = cr.dictfetchall()

    if not rows:
        return {}

    attachment_ids = list({row['att_id'] for row in rows})
    token_map = _ensure_attachment_access_tokens(env, attachment_ids)
    db_name = _current_database_name(env)
    download_headers = _attachment_download_headers(env)

    lookup = {}

    for row in rows:
        mid = row['message_id']
        att_id = row['att_id']

        token = row['att_token'] or token_map.get(att_id)

        if not token:
            _logger.warning(
                "[Zencore] Attachment id=%s has no access token. "
                "URL may require authenticated session.",
                att_id,
            )

        lookup.setdefault(mid, []).append({
            'id': att_id,
            'name': row['att_name'],
            'mimetype': row['att_mimetype'] or 'application/octet-stream',
            'url': _attachment_download_url(att_id, token, db_name),
            'headers': download_headers,
        })

    return lookup


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _json_response(data: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(data, default=str),
        status=status,
        content_type='application/json; charset=utf-8',
    )


def success_response(data, *, meta: dict = None) -> Response:
    payload = {'status': 'success', 'data': data}
    if meta:
        payload['meta'] = meta
    return _json_response(payload, 200)


def error_response(http_status: int, code: str, message: str) -> Response:
    return _json_response(
        {'status': 'error', 'error': {'code': code, 'message': message}},
        http_status,
    )


# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------

def require_api_key(fn):
    """
    Validate  ``Authorization: Bearer <key>``  against Odoo's built-in
    ``res.users.apikeys`` table (scope = 'rpc').

    On success  → re-scopes ``request.env`` to the key owner and calls fn.
    On failure  → returns a 401 JSON response immediately.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return error_response(
                401, 'MISSING_AUTH',
                'Authorization header required. '
                'Format: "Authorization: Bearer <api_key>"',
            )

        raw_key = auth_header[len('Bearer '):]

        try:
            uid = (
                request.env['res.users.apikeys']
                .sudo()
                ._check_credentials(scope='rpc', key=raw_key)
            )
        except (AccessError, ValueError):
            uid = None

        if not uid:
            return error_response(
                401, 'INVALID_API_KEY',
                'API key is invalid or has been revoked.',
            )

        request.update_env(user=uid)
        _logger.debug('API key resolved → uid=%s', uid)
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Partner resolution  (by student e-mail)
# ---------------------------------------------------------------------------

def resolve_partner_by_email(email: str):
    """
    Return the first ``res.partner`` whose e-mail matches *email*
    (case-insensitive exact match).

    Returns the partner record on success, or ``None`` when not found.
    Uses ``sudo()`` so the API key owner's access level never blocks the
    look-up of portal / public partner records.
    """
    if not email or not email.strip():
        return None
    Partner = request.env['res.partner'].sudo()
    partner = Partner.search([
        ('email', '=', email.strip()),
    ], limit=1)
    return partner or None


# ---------------------------------------------------------------------------
# Datetime helper
# ---------------------------------------------------------------------------

def _fmt_dt(dt) -> str | None:
    """ISO-8601 UTC string, or None."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _sender_name_from_email_from(email_from: str) -> str | None:
    """
    Extract the visible sender name from a mail.message ``email_from`` value.

    Odoo can keep the external sender in ``email_from`` while ``author_id`` is
    the Odoo user/partner that posted or processed the message.
    """
    if not email_from or not email_from.strip():
        return None

    name, email = parseaddr(email_from.strip())
    return (name or email or email_from).strip() or None


def _message_display_author(msg) -> str:
    """Return the sender-facing author name for API clients."""
    return (
        _sender_name_from_email_from(msg.email_from)
        or (msg.author_id.name if msg.author_id else None)
        or 'Unknown'
    )


# ---------------------------------------------------------------------------
# Ticket serialisers
# ---------------------------------------------------------------------------

def _get_ticket_help_topic(ticket) -> str:
    """Return help_topic when the custom field is installed."""
    if 'help_topic' not in ticket._fields:
        return ''
    return ticket.help_topic or ''


def serialize_ticket_list_item(ticket) -> dict:
    """
    Lightweight payload used in the **list** endpoint.

    Fields: id, ticket_ref, subject, help_topic, status, create_date.
    """
    return {
        'id':          ticket.id,
        'create_date': _fmt_dt(ticket.create_date),
        # 'ticket_ref':  ticket.ticket_ref or f'HD{ticket.id:05d}',
        'status':      ticket.stage_id.name if ticket.stage_id else None,
        'subject':     ticket.name,
        'help_topic':  _get_ticket_help_topic(ticket),
    }


def serialize_ticket_detail(ticket) -> dict:
    """
    Full payload used in the **detail** endpoint.

     Fields: id, ticket_ref, subject, help_topic, status, create_date,
           team, description, communication_history, attachments.
    """
    return {
        'id':                    ticket.id,
        # 'ticket_ref':            ticket.ticket_ref or f'HD{ticket.id:05d}',
        'subject':               ticket.name,
        'help_topic':            _get_ticket_help_topic(ticket),
        'status':                ticket.stage_id.name  if ticket.stage_id  else None,
        'create_date':           _fmt_dt(ticket.create_date),
        'team':                  ticket.team_id.name   if ticket.team_id   else None,
        'description':           ticket.description or '',
        'communication_history': _get_messages(ticket),
        'attachments':           _get_attachments(ticket),
    }


# ---------------------------------------------------------------------------
# Internal serialisation helpers
# ---------------------------------------------------------------------------

def _get_messages(ticket) -> list[dict]:
    """
    Return human-written chatter messages for the ticket, oldest first.

    Included:
        message_type in ('comment', 'email', 'email_outgoing')
        with a non-empty body.

    Excluded:
        automated notifications, system log-notes, empty messages.
    """
    messages = ticket.message_ids.filtered(
        lambda m: (
            m.message_type in ('comment', 'email', 'email_outgoing')
            and bool((m.body or '').strip())
        )
    ).sorted('date')

    message_ids = messages.ids

    attachment_lookup = _prefetch_message_attachments(
        request.env.cr,
        request.env,
        message_ids,
    )

    result = []

    for msg in messages:
        result.append({
            'id': msg.id,
            'date': _fmt_dt(msg.date),
            'author': _message_display_author(msg),
            'author_id': msg.author_id.id if msg.author_id else None,
            'email_from': msg.email_from or '',
            'message_type': msg.message_type,
            'body': msg.body,
            'attachments': attachment_lookup.get(msg.id, []),
        })

    return result


def _get_attachments(ticket) -> list[dict]:
    """
    All ir.attachment records linked directly to this helpdesk.ticket record.

    Returns tokenized downloadable URLs.
    """
    attachments = (
        request.env['ir.attachment']
        .sudo()
        .search([
            ('res_model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
        ])
    )

    token_map = _ensure_attachment_access_tokens(
        request.env,
        attachments.ids,
    )
    db_name = _current_database_name(request.env)
    download_headers = _attachment_download_headers(request.env)

    result = []

    for att in attachments:
        token = token_map.get(att.id)

        if not token:
            _logger.warning(
                "[Zencore] Ticket attachment id=%s has no access token. "
                "URL may require authenticated session.",
                att.id,
            )

        result.append({
            'id': att.id,
            'name': att.name,
            'mimetype': att.mimetype or 'application/octet-stream',
            'file_size': att.file_size,
            'url': _attachment_download_url(att.id, token, db_name),
            'headers': download_headers,
            'create_date': _fmt_dt(att.create_date),
        })

    return result
