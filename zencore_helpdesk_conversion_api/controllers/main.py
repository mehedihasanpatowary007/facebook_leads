# # # # # """
# # # # # zencore_helpdesk_conversion_api — controllers/main.py

# # # # # Endpoints
# # # # # ─────────
# # # # #   POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # # # #       Receive a portal message, log it as an internal chatter note,
# # # # #       notify the assigned agent.  (Section 2)

# # # # #   GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation
# # # # #       Return the ticket message history in one of three modes:

# # # # #         mode=tree   (default) — fully nested parent → children tree.
# # # # #                                 Best for collapsible / sidebar UIs.

# # # # #         mode=flat             — strict date-ascending flat list.
# # # # #                                 Ignores threading; good for simple logs.

# # # # #         mode=hybrid           — chronological DFS timeline.
# # # # #                                 Root messages ordered by date; each root's
# # # # #                                 replies follow immediately (depth-first) so
# # # # #                                 threads stay together without nesting.
# # # # #                                 Every message carries depth + thread_root_id
# # # # #                                 so the frontend can indent without recursion.

# # # # #   GET  /api/v1/helpdesk/ticket/<ticket_id>/message/<message_id>/thread
# # # # #       Return a single message and all its nested descendants only.

# # # # # Auth : None (public) on all three routes.

# # # # # Conversation design
# # # # # ───────────────────
# # # # #   mail.message.parent_id == False  → root / independent message
# # # # #   mail.message.parent_id != False  → threaded reply

# # # # #   The three modes above all draw from the same flat DB query; only the
# # # # #   serialisation step differs.  _serialise_message() is mode-agnostic.
# # # # # """

# # # # # import base64
# # # # # import binascii
# # # # # import json
# # # # # import logging
# # # # # import mimetypes
# # # # # from html.parser import HTMLParser

# # # # # from markupsafe import Markup, escape
# # # # # from werkzeug.utils import secure_filename

# # # # # from odoo import http
# # # # # from odoo.http import Response, request

# # # # # _logger = logging.getLogger(__name__)


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # Tiny HTML → plain-text stripper
# # # # # # mail.message bodies are stored as HTML; callers often need a readable preview.
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # class _HTMLStripper(HTMLParser):
# # # # #     def __init__(self):
# # # # #         super().__init__()
# # # # #         self._parts = []

# # # # #     def handle_data(self, data):
# # # # #         self._parts.append(data)

# # # # #     def get_text(self):
# # # # #         return ' '.join(self._parts).strip()


# # # # # def _strip_html(html):
# # # # #     if not html:
# # # # #         return ''
# # # # #     stripper = _HTMLStripper()
# # # # #     try:
# # # # #         stripper.feed(html)
# # # # #         return stripper.get_text()
# # # # #     except Exception:
# # # # #         return html


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # Author-type resolver
# # # # # #
# # # # # #   partner.user_ids  — all res.users records linked to this partner
# # # # # #   user.share        — True  → portal user
# # # # # #                     — False → internal (back-office) user
# # # # # #   No users at all   → public / external contact
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # def _resolve_author_type(partner):
# # # # #     """
# # # # #     Classify a partner as one of three mutually exclusive types:
# # # # #         'internal_user'  — Odoo back-office employee
# # # # #         'portal_user'    — authenticated portal customer
# # # # #         'public'         — unauthenticated / external contact
# # # # #     """
# # # # #     if not partner:
# # # # #         return 'public'
# # # # #     users = partner.user_ids
# # # # #     if not users:
# # # # #         return 'public'
# # # # #     for user in users:
# # # # #         if not user.share:
# # # # #             return 'internal_user'
# # # # #     return 'portal_user'


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # Message serialiser
# # # # # #
# # # # # # Converts one mail.message record into a plain dict.
# # # # # # Does NOT recurse — tree / hybrid assembly is done in dedicated functions.
# # # # # #
# # # # # # Fields returned:
# # # # # #   message_id          — DB id
# # # # # #   parent_id           — DB id of parent message (null if root/independent)
# # # # # #   body_html           — raw HTML body stored by Odoo
# # # # # #   body_text           — plain-text stripped version (preview / search)
# # # # # #   message_type        — 'comment' | 'email' | 'notification' | 'user_notification'
# # # # # #   subtype_name        — human-readable subtype label ('Note', 'Discussions', …)
# # # # # #   is_internal_note    — True when subtype is mail.mt_note
# # # # # #   direction           — 'inbound'  (from portal / external)
# # # # # #                          'outbound' (from assigned agent)
# # # # # #                          'internal' (other internal staff / system)
# # # # # #   date                — ISO-8601 UTC timestamp
# # # # # #   author              — nested author object (see below)
# # # # # #   reply_count         — number of direct children (populated during tree build)
# # # # # #   replies             — [] placeholder; filled by _build_tree() only
# # # # # #
# # # # # # Author object:
# # # # # #   id                  — res.partner id
# # # # # #   name                — display name
# # # # # #   email               — email address
# # # # # #   user_type           — 'internal_user' | 'portal_user' | 'public'
# # # # # #   is_assigned_agent   — True if this author is the ticket's assigned user
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # def _serialise_message(msg, ticket):
# # # # #     partner     = msg.author_id
# # # # #     author_type = _resolve_author_type(partner)

# # # # #     assigned_pid = (
# # # # #         ticket.user_id.partner_id.id
# # # # #         if ticket.user_id and ticket.user_id.partner_id
# # # # #         else False
# # # # #     )

# # # # #     # direction:
# # # # #     #   inbound  = sent by a portal/public user (came from outside Odoo)
# # # # #     #   outbound = sent by the assigned internal agent
# # # # #     #   internal = posted by any other internal user or the system
# # # # #     if author_type in ('portal_user', 'public'):
# # # # #         direction = 'inbound'
# # # # #     elif assigned_pid and partner and partner.id == assigned_pid:
# # # # #         direction = 'outbound'
# # # # #     else:
# # # # #         direction = 'internal'

# # # # #     subtype      = msg.subtype_id
# # # # #     mt_note_ref  = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # # # #     is_internal_note = bool(
# # # # #         subtype and mt_note_ref and subtype.id == mt_note_ref.id
# # # # #     )

# # # # #     return {
# # # # #         'message_id':       msg.id,
# # # # #         'parent_id':        msg.parent_id.id if msg.parent_id else None,
# # # # #         'body_html':        msg.body or '',
# # # # #         'body_text':        _strip_html(msg.body),
# # # # #         'message_type':     msg.message_type or '',
# # # # #         'subtype_name':     subtype.name if subtype else None,
# # # # #         'is_internal_note': is_internal_note,
# # # # #         'direction':        direction,
# # # # #         'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
# # # # #         'attachments':      [
# # # # #             {
# # # # #                 'id':       attachment.id,
# # # # #                 'name':     attachment.name,
# # # # #                 'mimetype': attachment.mimetype,
# # # # #                 'url':      '/web/content/%s?download=true' % attachment.id,
# # # # #             }
# # # # #             for attachment in msg.attachment_ids
# # # # #         ],
# # # # #         'author': {
# # # # #             'id':                partner.id if partner else None,
# # # # #             'name':              partner.name if partner else 'Unknown',
# # # # #             'email':             partner.email if partner else None,
# # # # #             'user_type':         author_type,
# # # # #             'is_assigned_agent': bool(
# # # # #                 assigned_pid and partner and partner.id == assigned_pid
# # # # #             ),
# # # # #         },
# # # # #         'reply_count': 0,
# # # # #         'replies':     [],
# # # # #     }


# # # # # def _normalise_orphan_parent_ids(flat_messages):
# # # # #     """Treat parents outside the returned conversation as root messages."""
# # # # #     message_ids = {msg['message_id'] for msg in flat_messages}
# # # # #     for msg in flat_messages:
# # # # #         if msg['parent_id'] and msg['parent_id'] not in message_ids:
# # # # #             msg['parent_id'] = None
# # # # #     return flat_messages


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # TREE builder — O(n)
# # # # # #
# # # # # # Converts a flat list of serialised dicts into a nested tree.
# # # # # #
# # # # # # Algorithm:
# # # # # #   1. Index every message by its message_id.
# # # # # #   2. Walk the list once; for each message that has a parent_id:
# # # # # #        - If the parent is in our set  → attach as a reply child.
# # # # # #        - If the parent is NOT in set  → treat as root (orphan root).
# # # # # #   3. Sort every level by date ascending (oldest-first, chat-window style).
# # # # # #
# # # # # # Output shape:
# # # # # #   [
# # # # # #     { "message_id": 10, "parent_id": null,
# # # # # #       "replies": [
# # # # # #         { "message_id": 11, "parent_id": 10,
# # # # # #           "replies": [ {"message_id": 13, "parent_id": 11, "replies": []} ]
# # # # # #         },
# # # # # #         { "message_id": 12, "parent_id": 10, "replies": [] }
# # # # # #       ]
# # # # # #     }
# # # # # #   ]
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # def _build_tree(flat_messages):
# # # # #     """Return fully nested conversation tree (mode=tree)."""
# # # # #     index = {m['message_id']: m for m in flat_messages}
# # # # #     roots = []

# # # # #     for msg in flat_messages:
# # # # #         pid = msg['parent_id']
# # # # #         if pid and pid in index:
# # # # #             parent = index[pid]
# # # # #             parent['replies'].append(msg)
# # # # #             parent['reply_count'] += 1
# # # # #         else:
# # # # #             roots.append(msg)

# # # # #     def _sort_level(nodes):
# # # # #         nodes.sort(key=lambda m: m['date'] or '')
# # # # #         for node in nodes:
# # # # #             if node['replies']:
# # # # #                 _sort_level(node['replies'])

# # # # #     _sort_level(roots)
# # # # #     return roots


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # HYBRID builder — O(n)
# # # # # #
# # # # # # Returns a flat, depth-annotated timeline where threads stay together.
# # # # # #
# # # # # # Strategy:
# # # # # #   1. Build a children map  { parent_id → [child, …] }  in one pass.
# # # # # #   2. Identify root messages (no parent, or parent outside this message set).
# # # # # #   3. Sort roots by date ascending.
# # # # # #   4. DFS from each root: emit the root, recurse into its children in date
# # # # # #      order, emit them, recurse further — this keeps all replies immediately
# # # # # #      adjacent to their thread root in chronological DFS order.
# # # # # #
# # # # # # Each message in the output gets two extra fields:
# # # # # #   depth           — nesting level (0 = root, 1 = direct reply, …)
# # # # # #   thread_root_id  — message_id of the root of the thread this belongs to
# # # # # #
# # # # # # The 'replies' key is stripped — it is irrelevant in a flat timeline.
# # # # # #
# # # # # # Example output:
# # # # # #   [
# # # # # #     { "message_id": 10, "parent_id": null,  "depth": 0, "thread_root_id": 10 },
# # # # # #     { "message_id": 11, "parent_id": 10,    "depth": 1, "thread_root_id": 10 },
# # # # # #     { "message_id": 13, "parent_id": 11,    "depth": 2, "thread_root_id": 10 },
# # # # # #     { "message_id": 12, "parent_id": 10,    "depth": 1, "thread_root_id": 10 },
# # # # # #     { "message_id": 20, "parent_id": null,  "depth": 0, "thread_root_id": 20 },
# # # # # #     { "message_id": 30, "parent_id": null,  "depth": 0, "thread_root_id": 30 },
# # # # # #     { "message_id": 31, "parent_id": 30,    "depth": 1, "thread_root_id": 30 },
# # # # # #   ]
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # def _build_hybrid(flat_messages):
# # # # #     """
# # # # #     Return a chronological DFS timeline with depth and thread_root_id metadata
# # # # #     (mode=hybrid).

# # # # #     Roots are ordered by their own date.  Within each thread the DFS walk
# # # # #     visits children in date-ascending order so the oldest reply appears before
# # # # #     newer siblings.
# # # # #     """
# # # # #     mid_set       = {m['message_id'] for m in flat_messages}
# # # # #     children_map  = {}   # { parent_id: [child_dict, …] }
# # # # #     roots         = []

# # # # #     for msg in flat_messages:
# # # # #         pid = msg['parent_id']
# # # # #         if pid and pid in mid_set:
# # # # #             children_map.setdefault(pid, []).append(msg)
# # # # #         else:
# # # # #             roots.append(msg)

# # # # #     # Sort roots and each children list by date, oldest first
# # # # #     roots.sort(key=lambda m: m['date'] or '')
# # # # #     for kids in children_map.values():
# # # # #         kids.sort(key=lambda m: m['date'] or '')

# # # # #     timeline = []

# # # # #     def _dfs(msg, depth, thread_root_id):
# # # # #         entry = {
# # # # #             k: v for k, v in msg.items()
# # # # #             if k not in ('replies',)          # strip tree-specific key
# # # # #         }
# # # # #         entry['depth']          = depth
# # # # #         entry['thread_root_id'] = thread_root_id
# # # # #         timeline.append(entry)
# # # # #         for child in children_map.get(msg['message_id'], []):
# # # # #             _dfs(child, depth + 1, thread_root_id)

# # # # #     for root in roots:
# # # # #         _dfs(root, 0, root['message_id'])

# # # # #     return timeline


# # # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # # Controller
# # # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # # class HelpdeskConversationController(http.Controller):

# # # # #     MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# # # # #     # =========================================================================
# # # # #     # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
# # # # #     # =========================================================================

# # # # #     @http.route(
# # # # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
# # # # #         type='http',
# # # # #         auth='public',
# # # # #         methods=['GET'],
# # # # #         csrf=False,
# # # # #         save_session=False,
# # # # #     )
# # # # #     def get_conversation(self, ticket_id, **query_params):
# # # # #         """
# # # # #         Return the ticket's full message history in one of three modes.

# # # # #         Query parameters (all optional):
# # # # #           mode              tree | flat | hybrid  (default: tree)
# # # # #           include_internal  1|0   Include mt_note internal notes  (default: 1)
# # # # #           include_system    1|0   Include system notifications    (default: 0)

# # # # #         ── mode=tree ──────────────────────────────────────────────────────────
# # # # #         Fully nested conversation tree.  Messages with parent_id appear inside
# # # # #         their parent's 'replies' list at unlimited depth.

# # # # #         Response shape:
# # # # #           {
# # # # #             "mode": "tree",
# # # # #             "conversation": [
# # # # #               {
# # # # #                 "message_id": 10, "parent_id": null,
# # # # #                 "reply_count": 2,
# # # # #                 "replies": [
# # # # #                   { "message_id": 11, "parent_id": 10,
# # # # #                     "reply_count": 1,
# # # # #                     "replies": [
# # # # #                       { "message_id": 13, "parent_id": 11,
# # # # #                         "reply_count": 0, "replies": [] }
# # # # #                     ]
# # # # #                   },
# # # # #                   { "message_id": 12, "parent_id": 10,
# # # # #                     "reply_count": 0, "replies": [] }
# # # # #                 ]
# # # # #               },
# # # # #               { "message_id": 20, "parent_id": null,
# # # # #                 "reply_count": 0, "replies": [] }
# # # # #             ]
# # # # #           }

# # # # #         ── mode=flat ──────────────────────────────────────────────────────────
# # # # #         Strict date-ascending flat list.  Threading fields (reply_count,
# # # # #         replies) are present but always 0/[].  No grouping.

# # # # #         Response shape:
# # # # #           {
# # # # #             "mode": "flat",
# # # # #             "conversation": [
# # # # #               { "message_id": 10, "parent_id": null,  … },
# # # # #               { "message_id": 11, "parent_id": 10,    … },
# # # # #               { "message_id": 13, "parent_id": 11,    … },
# # # # #               { "message_id": 12, "parent_id": 10,    … },
# # # # #               { "message_id": 20, "parent_id": null,  … }
# # # # #             ]
# # # # #           }

# # # # #         ── mode=hybrid ────────────────────────────────────────────────────────
# # # # #         Chronological DFS timeline.  Thread replies appear immediately after
# # # # #         their root, but no nesting in the JSON — purely flat with metadata.
# # # # #         'replies' key is omitted.

# # # # #         Response shape:
# # # # #           {
# # # # #             "mode": "hybrid",
# # # # #             "conversation": [
# # # # #               { "message_id": 10, "parent_id": null,  "depth": 0, "thread_root_id": 10 },
# # # # #               { "message_id": 11, "parent_id": 10,    "depth": 1, "thread_root_id": 10 },
# # # # #               { "message_id": 13, "parent_id": 11,    "depth": 2, "thread_root_id": 10 },
# # # # #               { "message_id": 12, "parent_id": 10,    "depth": 1, "thread_root_id": 10 },
# # # # #               { "message_id": 20, "parent_id": null,  "depth": 0, "thread_root_id": 20 }
# # # # #             ]
# # # # #           }

# # # # #         Full envelope (same for all modes):
# # # # #           {
# # # # #             "status":         "success",
# # # # #             "ticket_id":      12,
# # # # #             "ticket_name":    "Enrollment Issue",
# # # # #             "ticket_status":  "In Progress",
# # # # #             "assigned_agent": {"id": 5, "name": "Jane", "email": "jane@co.com"},
# # # # #             "total_messages": 8,
# # # # #             "mode":           "hybrid",
# # # # #             "conversation":   [ … ]
# # # # #           }

# # # # #         Error responses:
# # # # #           404 — ticket not found
# # # # #           400 — invalid mode value
# # # # #           500 — unexpected server error
# # # # #         """
# # # # #         # ── Query param parsing ──────────────────────────────────────────────
# # # # #         mode             = query_params.get('mode', 'tree').strip().lower()
# # # # #         include_internal = query_params.get('include_internal', '1') != '0'
# # # # #         include_system   = query_params.get('include_system',   '0') == '1'

# # # # #         if mode not in ('tree', 'flat', 'hybrid'):
# # # # #             return self._json_response(
# # # # #                 {
# # # # #                     "status":  "error",
# # # # #                     "message": "Invalid mode '%s'. Accepted values: tree, flat, hybrid." % mode,
# # # # #                 },
# # # # #                 status=400,
# # # # #             )

# # # # #         # ── Ticket lookup ────────────────────────────────────────────────────
# # # # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # # # #         if not ticket.exists():
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # # # #                 status=404,
# # # # #             )

# # # # #         # ── ORM domain ───────────────────────────────────────────────────────
# # # # #         allowed_types = ['comment', 'email']
# # # # #         if include_system:
# # # # #             allowed_types += ['notification', 'user_notification']

# # # # #         domain = [
# # # # #             ('model',        '=',  'helpdesk.ticket'),
# # # # #             ('res_id',       '=',  ticket_id),
# # # # #             ('message_type', 'in', allowed_types),
# # # # #         ]

# # # # #         if not include_internal:
# # # # #             mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # # # #             if mt_note:
# # # # #                 domain.append(('subtype_id', '!=', mt_note.id))

# # # # #         # ── Fetch messages ───────────────────────────────────────────────────
# # # # #         try:
# # # # #             messages = request.env['mail.message'].sudo().search(
# # # # #                 domain,
# # # # #                 order='date asc',
# # # # #             )
# # # # #         except Exception as exc:
# # # # #             _logger.error(
# # # # #                 "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
# # # # #                 ticket_id, exc,
# # # # #             )
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "Failed to retrieve conversation."},
# # # # #                 status=500,
# # # # #             )

# # # # #         flat_list = _normalise_orphan_parent_ids(
# # # # #             [_serialise_message(msg, ticket) for msg in messages]
# # # # #         )

# # # # #         # ── Build output in requested mode ───────────────────────────────────
# # # # #         if mode == 'tree':
# # # # #             conversation = _build_tree(flat_list)
# # # # #         elif mode == 'hybrid':
# # # # #             conversation = _build_hybrid(flat_list)
# # # # #         else:
# # # # #             # flat: flat_list is already date-sorted; return as-is
# # # # #             conversation = flat_list

# # # # #         # ── Assigned agent summary ───────────────────────────────────────────
# # # # #         assigned_agent = None
# # # # #         if ticket.user_id:
# # # # #             assigned_agent = {
# # # # #                 'id':    ticket.user_id.id,
# # # # #                 'name':  ticket.user_id.name,
# # # # #                 'email': ticket.user_id.email,
# # # # #             }

# # # # #         return self._json_response({
# # # # #             'status':         'success',
# # # # #             'ticket_id':      ticket.id,
# # # # #             'ticket_name':    ticket.name or '',
# # # # #             'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
# # # # #             'assigned_agent': assigned_agent,
# # # # #             'total_messages': len(flat_list),
# # # # #             'mode':           mode,
# # # # #             'conversation':   conversation,
# # # # #         })

# # # # #     # =========================================================================
# # # # #     # GET /api/v1/helpdesk/ticket/<ticket_id>/message/<message_id>/thread
# # # # #     #
# # # # #     # Return a SINGLE message and all its descendants only.
# # # # #     # Useful for lazy-loading one sub-thread without fetching the whole ticket.
# # # # #     # =========================================================================

# # # # #     # @http.route(
# # # # #     #     '/api/v1/helpdesk/ticket/<int:ticket_id>/message/<int:message_id>/thread',
# # # # #     #     type='http',
# # # # #     #     auth='public',
# # # # #     #     methods=['GET'],
# # # # #     #     csrf=False,
# # # # #     #     save_session=False,
# # # # #     # )
# # # # #     # def get_message_thread(self, ticket_id, message_id, **query_params):
# # # # #     #     """
# # # # #     #     Return a specific message and all its nested replies.

# # # # #     #     Query parameters (optional):
# # # # #     #       mode   tree | hybrid   (default: tree)
# # # # #     #              'flat' is not useful here — use the full conversation endpoint.

# # # # #     #     Success response (200) — mode=tree:
# # # # #     #       {
# # # # #     #         "status":     "success",
# # # # #     #         "ticket_id":  12,
# # # # #     #         "mode":       "tree",
# # # # #     #         "root": {
# # # # #     #           "message_id": 45, "parent_id": null,
# # # # #     #           "replies": [
# # # # #     #             { "message_id": 46,
# # # # #     #               "replies": [ {"message_id": 50, "replies": []} ]
# # # # #     #             }
# # # # #     #           ]
# # # # #     #         }
# # # # #     #       }

# # # # #     #     Success response (200) — mode=hybrid:
# # # # #     #       {
# # # # #     #         "status":     "success",
# # # # #     #         "ticket_id":  12,
# # # # #     #         "mode":       "hybrid",
# # # # #     #         "thread": [
# # # # #     #           { "message_id": 45, "depth": 0, "thread_root_id": 45 },
# # # # #     #           { "message_id": 46, "depth": 1, "thread_root_id": 45 },
# # # # #     #           { "message_id": 50, "depth": 2, "thread_root_id": 45 }
# # # # #     #         ]
# # # # #     #       }
# # # # #     #     """
# # # # #     #     mode = query_params.get('mode', 'tree').strip().lower()
# # # # #     #     if mode not in ('tree', 'hybrid'):
# # # # #     #         return self._json_response(
# # # # #     #             {
# # # # #     #                 "status":  "error",
# # # # #     #                 "message": "Invalid mode '%s' for this endpoint. Use tree or hybrid." % mode,
# # # # #     #             },
# # # # #     #             status=400,
# # # # #     #         )

# # # # #     #     # ── Ticket + message validation ──────────────────────────────────────
# # # # #     #     ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # # # #     #     if not ticket.exists():
# # # # #     #         return self._json_response(
# # # # #     #             {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # # # #     #             status=404,
# # # # #     #         )

# # # # #     #     root_msg = request.env['mail.message'].sudo().browse(message_id)
# # # # #     #     if (
# # # # #     #         not root_msg.exists()
# # # # #     #         or root_msg.model != 'helpdesk.ticket'
# # # # #     #         or root_msg.res_id != ticket_id
# # # # #     #     ):
# # # # #     #         return self._json_response(
# # # # #     #             {
# # # # #     #                 "status":  "error",
# # # # #     #                 "message": "Message #%s not found on ticket #%s." % (message_id, ticket_id),
# # # # #     #             },
# # # # #     #             status=404,
# # # # #     #         )

# # # # #     #     # ── Collect all descendants — iterative BFS over child_ids ───────────
# # # # #     #     # Avoids recursive SQL; works with any Odoo-supported PG version.
# # # # #     #     collected = {}
# # # # #     #     queue     = [root_msg]

# # # # #     #     while queue:
# # # # #     #         current_batch = queue
# # # # #     #         queue = []
# # # # #     #         for msg in current_batch:
# # # # #     #             if msg.id not in collected:
# # # # #     #                 collected[msg.id] = msg
# # # # #     #                 for child in msg.child_ids:
# # # # #     #                     queue.append(child)

# # # # #     #     flat_list = _normalise_orphan_parent_ids(
# # # # #     #         [_serialise_message(m, ticket) for m in collected.values()]
# # # # #     #     )

# # # # #     #     if mode == 'tree':
# # # # #     #         thread_tree = _build_tree(flat_list)
# # # # #     #         root_node   = next(
# # # # #     #             (n for n in thread_tree if n['message_id'] == message_id),
# # # # #     #             thread_tree[0] if thread_tree else None,
# # # # #     #         )
# # # # #     #         return self._json_response({
# # # # #     #             'status':    'success',
# # # # #     #             'ticket_id': ticket.id,
# # # # #     #             'mode':      'tree',
# # # # #     #             'root':      root_node,
# # # # #     #         })

# # # # #     #     # hybrid
# # # # #     #     thread = _build_hybrid(flat_list)
# # # # #     #     return self._json_response({
# # # # #     #         'status':    'success',
# # # # #     #         'ticket_id': ticket.id,
# # # # #     #         'mode':      'hybrid',
# # # # #     #         'thread':    thread,
# # # # #     #     })

# # # # #     # =========================================================================
# # # # #     # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # # # #     # =========================================================================

# # # # #     @http.route(
# # # # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
# # # # #         type='http',
# # # # #         auth='public',
# # # # #         methods=['POST'],
# # # # #         csrf=False,
# # # # #         save_session=False,
# # # # #     )
# # # # #     def inbound_message(self, ticket_id, **_kwargs):
# # # # #         """
# # # # #         Receive an inbound message from the external portal.

# # # # #         Request body (JSON):
# # # # #           {
# # # # #             "sender_name":       "John Doe",
# # # # #             "sender_email":      "john@example.com",
# # # # #             "body":              "Hello, I need help with my enrollment.",
# # # # #             "parent_message_id": null,  // or integer — links to a specific reply
# # # # #             "attachments": [
# # # # #               {"filename": "screenshot.png", "data": "<base64>", "mimetype": "image/png"}
# # # # #             ]
# # # # #           }

# # # # #         parent_message_id rules:
# # # # #           null    → independent root message (no thread relationship)
# # # # #           integer → threaded reply to that message_id

# # # # #         Success (200):
# # # # #           { "status": "success", "message_id": 45, "ticket_id": 12 }

# # # # #         Errors: 400 | 404 | 422 | 500
# # # # #         """
# # # # #         # ── Parse request body ───────────────────────────────────────────────
# # # # #         try:
# # # # #             payload, uploaded_files = self._parse_inbound_payload()
# # # # #         except ValueError as exc:
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": str(exc)},
# # # # #                 status=400,
# # # # #             )

# # # # #         sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
# # # # #         sender_email    = str(payload.get('sender_email', '')).strip()
# # # # #         body            = str(payload.get('body',         '')).strip()
# # # # #         raw_parent      = payload.get('parent_message_id')
# # # # #         raw_attachments = payload.get('attachments') or []

# # # # #         if not body and not raw_attachments and not uploaded_files:
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "'body' or 'attachments' is required."},
# # # # #                 status=422,
# # # # #             )

# # # # #         # ── Fetch ticket ─────────────────────────────────────────────────────
# # # # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # # # #         if not ticket.exists():
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # # # #                 status=404,
# # # # #             )

# # # # #         # ── Resolve author ───────────────────────────────────────────────────
# # # # #         # Inbound portal messages must look like customer messages in chatter.
# # # # #         # If the external sender is not in Odoo yet, create a lightweight contact
# # # # #         # instead of posting as OdooBot, otherwise direction/reply styling breaks.
# # # # #         author_id = False
# # # # #         if sender_email:
# # # # #             Partner = request.env['res.partner'].sudo()
# # # # #             partner = Partner.search([('email', '=', sender_email)], limit=1)
# # # # #             if not partner:
# # # # #                 partner = Partner.create({
# # # # #                     'name': sender_name or sender_email,
# # # # #                     'email': sender_email,
# # # # #                 })
# # # # #             author_id = partner.id

# # # # #         # ── Resolve optional parent_message_id ──────────────────────────────
# # # # #         parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

# # # # #         # ── Prepare optional inbound attachments ────────────────────────────
# # # # #         try:
# # # # #             attachments = self._prepare_inbound_attachments(raw_attachments)
# # # # #             attachments += self._prepare_uploaded_attachments(uploaded_files)
# # # # #         except ValueError as exc:
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": str(exc)},
# # # # #                 status=422,
# # # # #             )
# # # # #         except Exception as exc:
# # # # #             _logger.error(
# # # # #                 "[Zencore] Failed to create attachments for ticket_id=%s: %s",
# # # # #                 ticket_id, exc,
# # # # #             )
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "Failed to process attachments."},
# # # # #                 status=500,
# # # # #             )

# # # # #         # ── Build chatter body ───────────────────────────────────────────────
# # # # #         chatter_body = Markup("<p>%s</p>" % escape(body or ""))

# # # # #         # ── Post to chatter ──────────────────────────────────────────────────
# # # # #         # message_type='comment' + subtype_xmlid='mail.mt_note' → internal note.
# # # # #         # _notify_thread is overridden on helpdesk.ticket (Section 1) so no
# # # # #         # follower emails will be dispatched.
# # # # #         # OdooBot is the default author when author_id=False, which intentionally
# # # # #         # does NOT trigger the assigned-agent forward path in message_post().

# # # # #         try:
# # # # #             message = ticket.message_post(
# # # # #                 body=chatter_body,
# # # # #                 author_id=author_id or False,
# # # # #                 message_type='comment',
# # # # #                 subtype_xmlid='mail.mt_note',
# # # # #                 parent_id=parent_id or False,
# # # # #                 attachments=attachments,
# # # # #             )
# # # # #         except Exception as exc:
# # # # #             _logger.error(
# # # # #                 "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
# # # # #                 ticket_id, exc,
# # # # #             )
# # # # #             return self._json_response(
# # # # #                 {"status": "error", "message": "Failed to post message."},
# # # # #                 status=500,
# # # # #             )

# # # # #         # ── Notify assigned agent (Section 2) ────────────────────────────────
# # # # #         ticket._notify_assigned_user_on_inbound()

# # # # #         return self._json_response({
# # # # #             "status":         "success",
# # # # #             "message_id":     message.id,
# # # # #             "ticket_id":      ticket.id,
# # # # #             "attachment_ids": message.attachment_ids.ids,
# # # # #         })

# # # # #     # ─────────────────────────────────────────────────────────────────────────
# # # # #     # Shared private helpers
# # # # #     # ─────────────────────────────────────────────────────────────────────────

# # # # #     def _parse_inbound_payload(self):
# # # # #         """Support JSON base64 attachments and Postman multipart/form-data files."""
# # # # #         content_type = (request.httprequest.content_type or '').lower()
# # # # #         if content_type.startswith('multipart/form-data'):
# # # # #             payload = dict(request.httprequest.form.items())
# # # # #             attachments = payload.get('attachments')
# # # # #             if attachments:
# # # # #                 try:
# # # # #                     payload['attachments'] = json.loads(attachments)
# # # # #                 except (TypeError, ValueError):
# # # # #                     raise ValueError("'attachments' must be valid JSON when sent as form-data.")

# # # # #             uploaded_files = []
# # # # #             for field_name in ('file', 'files', 'attachments_file'):
# # # # #                 uploaded_files.extend(request.httprequest.files.getlist(field_name))
# # # # #             return payload, uploaded_files

# # # # #         raw = request.httprequest.data
# # # # #         if not raw:
# # # # #             raise ValueError('Empty request body.')
# # # # #         try:
# # # # #             return json.loads(raw), []
# # # # #         except (ValueError, TypeError) as exc:
# # # # #             _logger.warning("[Zencore] Malformed JSON in inbound_message: %s", exc)
# # # # #             raise ValueError('Invalid JSON payload.')

# # # # #     @staticmethod
# # # # #     def _prepare_inbound_attachments(raw_attachments):
# # # # #         """Return message_post attachment tuples from JSON base64 payloads."""
# # # # #         if not isinstance(raw_attachments, list):
# # # # #             raise ValueError("'attachments' must be a list.")

# # # # #         attachments = []
# # # # #         for index, item in enumerate(raw_attachments, start=1):
# # # # #             if not isinstance(item, dict):
# # # # #                 raise ValueError("Attachment #%s must be an object." % index)

# # # # #             filename = HelpdeskConversationController._clean_filename(
# # # # #                 item.get('filename') or item.get('name') or 'attachment-%s' % index
# # # # #             )
# # # # #             raw_data = item.get('data') or item.get('datas') or item.get('content')
# # # # #             if not raw_data:
# # # # #                 raise ValueError("Attachment '%s' is missing base64 data." % filename)

# # # # #             raw_data = str(raw_data).strip()
# # # # #             if ',' in raw_data and raw_data.lower().startswith('data:'):
# # # # #                 raw_data = raw_data.split(',', 1)[1]

# # # # #             try:
# # # # #                 file_content = base64.b64decode(raw_data, validate=True)
# # # # #             except (binascii.Error, ValueError):
# # # # #                 raise ValueError("Attachment '%s' has invalid base64 data." % filename)

# # # # #             HelpdeskConversationController._check_attachment_size(filename, file_content)
# # # # #             attachments.append((filename, file_content))
# # # # #         return attachments

# # # # #     @staticmethod
# # # # #     def _prepare_uploaded_attachments(uploaded_files):
# # # # #         """Return message_post attachment tuples from multipart FileStorage objects."""
# # # # #         attachments = []
# # # # #         for uploaded_file in uploaded_files:
# # # # #             if not uploaded_file or not uploaded_file.filename:
# # # # #                 continue
# # # # #             filename = HelpdeskConversationController._clean_filename(uploaded_file.filename)
# # # # #             file_content = uploaded_file.read()
# # # # #             HelpdeskConversationController._check_attachment_size(filename, file_content)
# # # # #             attachments.append((filename, file_content))
# # # # #         return attachments

# # # # #     @staticmethod
# # # # #     def _check_attachment_size(filename, file_content):
# # # # #         if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
# # # # #             raise ValueError("Attachment '%s' exceeds 10MB limit." % filename)

# # # # #     @staticmethod
# # # # #     def _clean_filename(filename):
# # # # #         filename = secure_filename(str(filename or '').strip())
# # # # #         return filename or 'attachment'


# # # # #     @staticmethod
# # # # #     def _json_response(data, status=200):
# # # # #         """Serialize data to a JSON HTTP response with an explicit status code."""
# # # # #         return Response(
# # # # #             json.dumps(data, default=str),
# # # # #             content_type='application/json; charset=utf-8',
# # # # #             status=status,
# # # # #         )

# # # # #     @staticmethod
# # # # #     def _resolve_parent_message_id(raw_parent, ticket_id):
# # # # #         """
# # # # #         Validate and resolve an optional parent_message_id from the request.

# # # # #         Returns a valid mail.message integer id or False.
# # # # #         Logs a warning and returns False if the value is invalid or the
# # # # #         referenced message does not exist.

# # # # #         All callers must pass parent_message_id through this method so the
# # # # #         value is consistently validated before being stored in the DB.
# # # # #         """
# # # # #         if raw_parent is None:
# # # # #             return False

# # # # #         try:
# # # # #             parent_int = int(raw_parent)
# # # # #         except (ValueError, TypeError):
# # # # #             _logger.warning(
# # # # #                 "[Zencore] parent_message_id='%s' is not an integer "
# # # # #                 "(ticket_id=%s). Ignoring.",
# # # # #                 raw_parent, ticket_id,
# # # # #             )
# # # # #             return False

# # # # #         parent_msg = request.env['mail.message'].sudo().browse(parent_int)
# # # # #         if not parent_msg.exists():
# # # # #             _logger.warning(
# # # # #                 "[Zencore] parent_message_id=%s does not exist "
# # # # #                 "(ticket_id=%s). Ignoring.",
# # # # #                 parent_int, ticket_id,
# # # # #             )
# # # # #             return False

# # # # #         if parent_msg.model != 'helpdesk.ticket' or parent_msg.res_id != ticket_id:
# # # # #             _logger.warning(
# # # # #                 "[Zencore] parent_message_id=%s does not belong to ticket_id=%s. Ignoring.",
# # # # #                 parent_int, ticket_id,
# # # # #             )
# # # # #             return False

# # # # #         return parent_msg.id

# # # # """
# # # # zencore_helpdesk_conversion_api — controllers/main.py

# # # # Endpoints
# # # # ─────────
# # # #   POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # # #       Receive a portal message, log it as an internal chatter note,
# # # #       notify the assigned agent.  (Section 2)

# # # #   GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation
# # # #       Return the ticket message history in one of three modes:

# # # #         mode=tree   (default) — fully nested parent → children tree.
# # # #         mode=flat             — strict date-ascending flat list.
# # # #         mode=hybrid           — chronological DFS timeline.

# # # # Auth : None (public) on all three routes.
# # # # """

# # # # import base64
# # # # import binascii
# # # # import json
# # # # import logging
# # # # import mimetypes
# # # # from html.parser import HTMLParser

# # # # from markupsafe import Markup, escape
# # # # from werkzeug.utils import secure_filename

# # # # from odoo import http
# # # # from odoo.http import Response, request

# # # # _logger = logging.getLogger(__name__)


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Tiny HTML → plain-text stripper
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # class _HTMLStripper(HTMLParser):
# # # #     def __init__(self):
# # # #         super().__init__()
# # # #         self._parts = []

# # # #     def handle_data(self, data):
# # # #         self._parts.append(data)

# # # #     def get_text(self):
# # # #         return ' '.join(self._parts).strip()


# # # # def _strip_html(html):
# # # #     if not html:
# # # #         return ''
# # # #     stripper = _HTMLStripper()
# # # #     try:
# # # #         stripper.feed(html)
# # # #         return stripper.get_text()
# # # #     except Exception:
# # # #         return html


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Author-type resolver
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # def _resolve_author_type(partner):
# # # #     """
# # # #     Classify a partner as one of three mutually exclusive types:
# # # #         'internal_user'  — Odoo back-office employee
# # # #         'portal_user'    — authenticated portal customer
# # # #         'public'         — unauthenticated / external contact
# # # #     """
# # # #     if not partner:
# # # #         return 'public'
# # # #     users = partner.user_ids
# # # #     if not users:
# # # #         return 'public'
# # # #     for user in users:
# # # #         if not user.share:
# # # #             return 'internal_user'
# # # #     return 'portal_user'


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Message serialiser
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # def _serialise_message(msg, ticket):
# # # #     partner     = msg.author_id
# # # #     author_type = _resolve_author_type(partner)

# # # #     assigned_pid = (
# # # #         ticket.user_id.partner_id.id
# # # #         if ticket.user_id and ticket.user_id.partner_id
# # # #         else False
# # # #     )

# # # #     if author_type in ('portal_user', 'public'):
# # # #         direction = 'inbound'
# # # #     elif assigned_pid and partner and partner.id == assigned_pid:
# # # #         direction = 'outbound'
# # # #     else:
# # # #         direction = 'internal'

# # # #     subtype      = msg.subtype_id
# # # #     mt_note_ref  = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # # #     is_internal_note = bool(
# # # #         subtype and mt_note_ref and subtype.id == mt_note_ref.id
# # # #     )

# # # #     return {
# # # #         'message_id':       msg.id,
# # # #         'parent_id':        msg.parent_id.id if msg.parent_id else None,
# # # #         'body_html':        msg.body or '',
# # # #         'body_text':        _strip_html(msg.body),
# # # #         'message_type':     msg.message_type or '',
# # # #         'subtype_name':     subtype.name if subtype else None,
# # # #         'is_internal_note': is_internal_note,
# # # #         'direction':        direction,
# # # #         'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
# # # #         'attachments':      [
# # # #             {
# # # #                 'id':       attachment.id,
# # # #                 'name':     attachment.name,
# # # #                 'mimetype': attachment.mimetype,
# # # #                 'url':      '/web/content/%s?download=true' % attachment.id,
# # # #             }
# # # #             for attachment in msg.attachment_ids
# # # #         ],
# # # #         'author': {
# # # #             'id':                partner.id if partner else None,
# # # #             'name':              partner.name if partner else 'Unknown',
# # # #             'email':             partner.email if partner else None,
# # # #             'user_type':         author_type,
# # # #             'is_assigned_agent': bool(
# # # #                 assigned_pid and partner and partner.id == assigned_pid
# # # #             ),
# # # #         },
# # # #         'reply_count': 0,
# # # #         'replies':     [],
# # # #     }


# # # # def _normalise_orphan_parent_ids(flat_messages):
# # # #     """Treat parents outside the returned conversation as root messages."""
# # # #     message_ids = {msg['message_id'] for msg in flat_messages}
# # # #     for msg in flat_messages:
# # # #         if msg['parent_id'] and msg['parent_id'] not in message_ids:
# # # #             msg['parent_id'] = None
# # # #     return flat_messages


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # TREE builder
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # def _build_tree(flat_messages):
# # # #     """Return fully nested conversation tree (mode=tree)."""
# # # #     index = {m['message_id']: m for m in flat_messages}
# # # #     roots = []

# # # #     for msg in flat_messages:
# # # #         pid = msg['parent_id']
# # # #         if pid and pid in index:
# # # #             parent = index[pid]
# # # #             parent['replies'].append(msg)
# # # #             parent['reply_count'] += 1
# # # #         else:
# # # #             roots.append(msg)

# # # #     def _sort_level(nodes):
# # # #         nodes.sort(key=lambda m: m['date'] or '')
# # # #         for node in nodes:
# # # #             if node['replies']:
# # # #                 _sort_level(node['replies'])

# # # #     _sort_level(roots)
# # # #     return roots


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # HYBRID builder
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # def _build_hybrid(flat_messages):
# # # #     """Return a chronological DFS timeline with depth + thread_root_id (mode=hybrid)."""
# # # #     mid_set       = {m['message_id'] for m in flat_messages}
# # # #     children_map  = {}
# # # #     roots         = []

# # # #     for msg in flat_messages:
# # # #         pid = msg['parent_id']
# # # #         if pid and pid in mid_set:
# # # #             children_map.setdefault(pid, []).append(msg)
# # # #         else:
# # # #             roots.append(msg)

# # # #     roots.sort(key=lambda m: m['date'] or '')
# # # #     for kids in children_map.values():
# # # #         kids.sort(key=lambda m: m['date'] or '')

# # # #     timeline = []

# # # #     def _dfs(msg, depth, thread_root_id):
# # # #         entry = {k: v for k, v in msg.items() if k not in ('replies',)}
# # # #         entry['depth']          = depth
# # # #         entry['thread_root_id'] = thread_root_id
# # # #         timeline.append(entry)
# # # #         for child in children_map.get(msg['message_id'], []):
# # # #             _dfs(child, depth + 1, thread_root_id)

# # # #     for root in roots:
# # # #         _dfs(root, 0, root['message_id'])

# # # #     return timeline


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Controller
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # class HelpdeskConversationController(http.Controller):

# # # #     MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# # # #     # =========================================================================
# # # #     # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
# # # #     # =========================================================================

# # # #     @http.route(
# # # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
# # # #         type='http',
# # # #         auth='public',
# # # #         methods=['GET'],
# # # #         csrf=False,
# # # #         save_session=False,
# # # #     )
# # # #     def get_conversation(self, ticket_id, **query_params):
# # # #         mode             = query_params.get('mode', 'tree').strip().lower()
# # # #         include_internal = query_params.get('include_internal', '1') != '0'
# # # #         include_system   = query_params.get('include_system',   '0') == '1'

# # # #         if mode not in ('tree', 'flat', 'hybrid'):
# # # #             return self._json_response(
# # # #                 {
# # # #                     "status":  "error",
# # # #                     "message": "Invalid mode '%s'. Accepted values: tree, flat, hybrid." % mode,
# # # #                 },
# # # #                 status=400,
# # # #             )

# # # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # # #         if not ticket.exists():
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # # #                 status=404,
# # # #             )

# # # #         allowed_types = ['comment', 'email']
# # # #         if include_system:
# # # #             allowed_types += ['notification', 'user_notification']

# # # #         domain = [
# # # #             ('model',        '=',  'helpdesk.ticket'),
# # # #             ('res_id',       '=',  ticket_id),
# # # #             ('message_type', 'in', allowed_types),
# # # #         ]

# # # #         if not include_internal:
# # # #             mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # # #             if mt_note:
# # # #                 domain.append(('subtype_id', '!=', mt_note.id))

# # # #         try:
# # # #             messages = request.env['mail.message'].sudo().search(
# # # #                 domain,
# # # #                 order='date asc',
# # # #             )
# # # #         except Exception as exc:
# # # #             _logger.error(
# # # #                 "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
# # # #                 ticket_id, exc,
# # # #             )
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Failed to retrieve conversation."},
# # # #                 status=500,
# # # #             )

# # # #         flat_list = _normalise_orphan_parent_ids(
# # # #             [_serialise_message(msg, ticket) for msg in messages]
# # # #         )

# # # #         if mode == 'tree':
# # # #             conversation = _build_tree(flat_list)
# # # #         elif mode == 'hybrid':
# # # #             conversation = _build_hybrid(flat_list)
# # # #         else:
# # # #             conversation = flat_list

# # # #         assigned_agent = None
# # # #         if ticket.user_id:
# # # #             assigned_agent = {
# # # #                 'id':    ticket.user_id.id,
# # # #                 'name':  ticket.user_id.name,
# # # #                 'email': ticket.user_id.email,
# # # #             }

# # # #         return self._json_response({
# # # #             'status':         'success',
# # # #             'ticket_id':      ticket.id,
# # # #             'ticket_name':    ticket.name or '',
# # # #             'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
# # # #             'assigned_agent': assigned_agent,
# # # #             'total_messages': len(flat_list),
# # # #             'mode':           mode,
# # # #             'conversation':   conversation,
# # # #         })

# # # #     # =========================================================================
# # # #     # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # # #     # =========================================================================

# # # #     @http.route(
# # # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
# # # #         type='http',
# # # #         auth='public',
# # # #         methods=['POST'],
# # # #         csrf=False,
# # # #         save_session=False,
# # # #     )
# # # #     def inbound_message(self, ticket_id, **_kwargs):
# # # #         """
# # # #         Receive an inbound message from the external portal.

# # # #         Request body (JSON):
# # # #           {
# # # #             "sender_name":       "John Doe",
# # # #             "sender_email":      "john@example.com",
# # # #             "body":              "Hello, I need help with my enrollment.",
# # # #             "parent_message_id": null,
# # # #             "attachments": [
# # # #               {"filename": "screenshot.png", "data": "<base64>", "mimetype": "image/png"}
# # # #             ]
# # # #           }

# # # #         Multipart/form-data is also accepted; files can be sent in the
# # # #         'file', 'files', or 'attachments_file' fields.

# # # #         Success (200):
# # # #           { "status": "success", "message_id": 45, "ticket_id": 12,
# # # #             "attachment_ids": [67, 68] }

# # # #         Errors: 400 | 404 | 422 | 500
# # # #         """
# # # #         # ── Parse request body ───────────────────────────────────────────────
# # # #         try:
# # # #             payload, uploaded_files = self._parse_inbound_payload()
# # # #         except ValueError as exc:
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": str(exc)},
# # # #                 status=400,
# # # #             )

# # # #         sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
# # # #         sender_email    = str(payload.get('sender_email', '')).strip()
# # # #         body            = str(payload.get('body',         '')).strip()
# # # #         raw_parent      = payload.get('parent_message_id')
# # # #         raw_attachments = payload.get('attachments') or []

# # # #         if not body and not raw_attachments and not uploaded_files:
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "'body' or 'attachments' is required."},
# # # #                 status=422,
# # # #             )

# # # #         # ── Fetch ticket ─────────────────────────────────────────────────────
# # # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # # #         if not ticket.exists():
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # # #                 status=404,
# # # #             )

# # # #         # ── Resolve author ───────────────────────────────────────────────────
# # # #         author_id = False
# # # #         if sender_email:
# # # #             Partner = request.env['res.partner'].sudo()
# # # #             partner = Partner.search([('email', '=', sender_email)], limit=1)
# # # #             if not partner:
# # # #                 partner = Partner.create({
# # # #                     'name': sender_name or sender_email,
# # # #                     'email': sender_email,
# # # #                 })
# # # #             author_id = partner.id

# # # #         # ── Resolve optional parent_message_id ──────────────────────────────
# # # #         parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

# # # #         # ── Validate & decode attachments ────────────────────────────────────
# # # #         # Both helpers now return (filename, bytes, mimetype) tuples.
# # # #         # Validation (size, base64 integrity) happens here — before any DB write.
# # # #         try:
# # # #             attachment_tuples = self._prepare_inbound_attachments(raw_attachments)
# # # #             attachment_tuples += self._prepare_uploaded_attachments(uploaded_files)
# # # #         except ValueError as exc:
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": str(exc)},
# # # #                 status=422,
# # # #             )
# # # #         except Exception as exc:
# # # #             _logger.error(
# # # #                 "[Zencore] Failed to process attachments for ticket_id=%s: %s",
# # # #                 ticket_id, exc,
# # # #             )
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Failed to process attachments."},
# # # #                 status=500,
# # # #             )

# # # #         # ── Create ir.attachment records BEFORE message_post ─────────────────
# # # #         # WHY: message_post(attachments=[(name, bytes)]) in Odoo 19 is
# # # #         # unreliable under auth='public' + sudo() — res_model/res_id linkage
# # # #         # is not guaranteed, causing attachments to become orphaned.
# # # #         # Creating ir.attachment records explicitly with sudo() and then
# # # #         # passing attachment_ids=[...] mirrors handle_file_upload() in the
# # # #         # ticket-creation controller and is the correct Odoo 19 pattern.
# # # #         try:
# # # #             attachment_ids = self._create_attachments_for_ticket(
# # # #                 ticket, attachment_tuples
# # # #             )
# # # #         except Exception as exc:
# # # #             _logger.error(
# # # #                 "[Zencore] Failed to create ir.attachment records for ticket_id=%s: %s",
# # # #                 ticket_id, exc,
# # # #             )
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Failed to save attachments."},
# # # #                 status=500,
# # # #             )

# # # #         # ── Build chatter body ───────────────────────────────────────────────
# # # #         chatter_body = Markup("<p>%s</p>" % escape(body or ""))

# # # #         # ── Post to chatter ──────────────────────────────────────────────────
# # # #         try:
# # # #             message = ticket.message_post(
# # # #                 body=chatter_body,
# # # #                 author_id=author_id or False,
# # # #                 message_type='comment',
# # # #                 subtype_xmlid='mail.mt_note',
# # # #                 parent_id=parent_id or False,
# # # #                 attachment_ids=attachment_ids,   # ← pre-created IDs, not raw tuples
# # # #             )
# # # #         except Exception as exc:
# # # #             _logger.error(
# # # #                 "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
# # # #                 ticket_id, exc,
# # # #             )
# # # #             return self._json_response(
# # # #                 {"status": "error", "message": "Failed to post message."},
# # # #                 status=500,
# # # #             )

# # # #         # ── Notify assigned agent ────────────────────────────────────────────
# # # #         ticket._notify_assigned_user_on_inbound()

# # # #         return self._json_response({
# # # #             "status":         "success",
# # # #             "message_id":     message.id,
# # # #             "ticket_id":      ticket.id,
# # # #             "attachment_ids": message.attachment_ids.ids,
# # # #         })

# # # #     # ─────────────────────────────────────────────────────────────────────────
# # # #     # Shared private helpers
# # # #     # ─────────────────────────────────────────────────────────────────────────

# # # #     def _parse_inbound_payload(self):
# # # #         """Support JSON base64 attachments and multipart/form-data file uploads."""
# # # #         content_type = (request.httprequest.content_type or '').lower()
# # # #         if content_type.startswith('multipart/form-data'):
# # # #             payload = dict(request.httprequest.form.items())
# # # #             attachments = payload.get('attachments')
# # # #             if attachments:
# # # #                 try:
# # # #                     payload['attachments'] = json.loads(attachments)
# # # #                 except (TypeError, ValueError):
# # # #                     raise ValueError(
# # # #                         "'attachments' must be valid JSON when sent as form-data."
# # # #                     )

# # # #             uploaded_files = []
# # # #             for field_name in ('file', 'files', 'attachments_file'):
# # # #                 uploaded_files.extend(request.httprequest.files.getlist(field_name))
# # # #             return payload, uploaded_files

# # # #         raw = request.httprequest.data
# # # #         if not raw:
# # # #             raise ValueError('Empty request body.')
# # # #         try:
# # # #             return json.loads(raw), []
# # # #         except (ValueError, TypeError) as exc:
# # # #             _logger.warning("[Zencore] Malformed JSON in inbound_message: %s", exc)
# # # #             raise ValueError('Invalid JSON payload.')

# # # #     @staticmethod
# # # #     def _prepare_inbound_attachments(raw_attachments):
# # # #         """
# # # #         Decode and validate base64 attachments from a JSON payload.

# # # #         Returns a list of (filename, file_bytes, mimetype) tuples.
# # # #         Raises ValueError on the first invalid entry so the caller can
# # # #         return a 422 before touching the DB.
# # # #         """
# # # #         if not isinstance(raw_attachments, list):
# # # #             raise ValueError("'attachments' must be a list.")

# # # #         attachments = []
# # # #         for index, item in enumerate(raw_attachments, start=1):
# # # #             if not isinstance(item, dict):
# # # #                 raise ValueError("Attachment #%s must be an object." % index)

# # # #             filename = HelpdeskConversationController._clean_filename(
# # # #                 item.get('filename') or item.get('name') or 'attachment-%s' % index
# # # #             )
# # # #             raw_data = item.get('data') or item.get('datas') or item.get('content')
# # # #             if not raw_data:
# # # #                 raise ValueError("Attachment '%s' is missing base64 data." % filename)

# # # #             raw_data = str(raw_data).strip()
# # # #             # Strip data-URI prefix:  "data:image/png;base64,<data>"
# # # #             if ',' in raw_data and raw_data.lower().startswith('data:'):
# # # #                 raw_data = raw_data.split(',', 1)[1]

# # # #             try:
# # # #                 file_content = base64.b64decode(raw_data, validate=True)
# # # #             except (binascii.Error, ValueError):
# # # #                 raise ValueError("Attachment '%s' has invalid base64 data." % filename)

# # # #             HelpdeskConversationController._check_attachment_size(filename, file_content)

# # # #             # Use caller-supplied mimetype first, then guess from filename
# # # #             mimetype = (
# # # #                 item.get('mimetype')
# # # #                 or mimetypes.guess_type(filename)[0]
# # # #                 or 'application/octet-stream'
# # # #             )
# # # #             attachments.append((filename, file_content, mimetype))
# # # #         return attachments

# # # #     @staticmethod
# # # #     def _prepare_uploaded_attachments(uploaded_files):
# # # #         """
# # # #         Read and validate files from a multipart/form-data upload.

# # # #         Returns a list of (filename, file_bytes, mimetype) tuples.
# # # #         """
# # # #         attachments = []
# # # #         for uploaded_file in uploaded_files:
# # # #             if not uploaded_file or not uploaded_file.filename:
# # # #                 continue
# # # #             filename     = HelpdeskConversationController._clean_filename(
# # # #                 uploaded_file.filename
# # # #             )
# # # #             file_content = uploaded_file.read()
# # # #             HelpdeskConversationController._check_attachment_size(filename, file_content)
# # # #             mimetype = (
# # # #                 uploaded_file.mimetype
# # # #                 or mimetypes.guess_type(filename)[0]
# # # #                 or 'application/octet-stream'
# # # #             )
# # # #             attachments.append((filename, file_content, mimetype))
# # # #         return attachments

# # # #     def _create_attachments_for_ticket(self, ticket, attachment_tuples):
# # # #         """
# # # #         Create ir.attachment records explicitly linked to the ticket and
# # # #         return their IDs.

# # # #         WHY this method exists instead of passing attachments= to message_post:
# # # #         ────────────────────────────────────────────────────────────────────────
# # # #         message_post(attachments=[(name, bytes)]) in Odoo 19 delegates
# # # #         ir.attachment creation to internal ORM helpers.  Under an
# # # #         auth='public' + sudo() call stack the res_model / res_id assignment
# # # #         is not guaranteed, which causes files to become orphaned — they are
# # # #         saved to the DB but not visible on the ticket chatter.

# # # #         Creating records with sudo() here and passing attachment_ids=[...]
# # # #         to message_post is the correct Odoo 19 pattern.  It mirrors
# # # #         handle_file_upload() in the ticket-creation controller of this
# # # #         same module.

# # # #         Returns [] when attachment_tuples is empty (no-op, safe to call
# # # #         unconditionally).
# # # #         """
# # # #         if not attachment_tuples:
# # # #             return []

# # # #         ids = []
# # # #         for filename, file_content, mimetype in attachment_tuples:
# # # #             attachment = request.env['ir.attachment'].sudo().create({
# # # #                 'name':      filename,
# # # #                 'type':      'binary',
# # # #                 'datas':     base64.b64encode(file_content),
# # # #                 'mimetype':  mimetype,
# # # #                 'res_model': 'helpdesk.ticket',
# # # #                 'res_id':    ticket.id,
# # # #             })
# # # #             ids.append(attachment.id)
# # # #             _logger.debug(
# # # #                 "[Zencore] Created attachment id=%s name='%s' for ticket_id=%s",
# # # #                 attachment.id, filename, ticket.id,
# # # #             )
# # # #         return ids

# # # #     @staticmethod
# # # #     def _check_attachment_size(filename, file_content):
# # # #         if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
# # # #             raise ValueError("Attachment '%s' exceeds 10MB limit." % filename)

# # # #     @staticmethod
# # # #     def _clean_filename(filename):
# # # #         filename = secure_filename(str(filename or '').strip())
# # # #         return filename or 'attachment'

# # # #     @staticmethod
# # # #     def _json_response(data, status=200):
# # # #         """Serialize data to a JSON HTTP response with an explicit status code."""
# # # #         return Response(
# # # #             json.dumps(data, default=str),
# # # #             content_type='application/json; charset=utf-8',
# # # #             status=status,
# # # #         )

# # # #     @staticmethod
# # # #     def _resolve_parent_message_id(raw_parent, ticket_id):
# # # #         """
# # # #         Validate and resolve an optional parent_message_id from the request.

# # # #         Returns a valid mail.message integer id or False.
# # # #         Logs a warning and returns False if the value is invalid or the
# # # #         referenced message does not exist on this ticket.
# # # #         """
# # # #         if raw_parent is None:
# # # #             return False

# # # #         try:
# # # #             parent_int = int(raw_parent)
# # # #         except (ValueError, TypeError):
# # # #             _logger.warning(
# # # #                 "[Zencore] parent_message_id='%s' is not an integer "
# # # #                 "(ticket_id=%s). Ignoring.",
# # # #                 raw_parent, ticket_id,
# # # #             )
# # # #             return False

# # # #         parent_msg = request.env['mail.message'].sudo().browse(parent_int)
# # # #         if not parent_msg.exists():
# # # #             _logger.warning(
# # # #                 "[Zencore] parent_message_id=%s does not exist "
# # # #                 "(ticket_id=%s). Ignoring.",
# # # #                 parent_int, ticket_id,
# # # #             )
# # # #             return False

# # # #         if parent_msg.model != 'helpdesk.ticket' or parent_msg.res_id != ticket_id:
# # # #             _logger.warning(
# # # #                 "[Zencore] parent_message_id=%s does not belong to ticket_id=%s. Ignoring.",
# # # #                 parent_int, ticket_id,
# # # #             )
# # # #             return False

# # # #         return parent_msg.id

# # # """
# # # zencore_helpdesk_conversion_api — controllers/main.py

# # # Endpoints
# # # ─────────
# # #   POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # #   GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation

# # # Auth: public on all routes.

# # # Attachment design (Odoo 19)
# # # ───────────────────────────
# # # message_post(attachment_ids=[...]) passes IDs through
# # # _message_post_process_attachments which silently drops any attachment
# # # whose res_model is already set to something other than
# # # 'mail.compose.message'.

# # # Correct pattern:
# # #   1. Post the message (body only, no attachments).
# # #   2. Create ir.attachment with res_model='helpdesk.ticket', res_id=ticket.id
# # #      so the files appear in the ticket's Attachments tab.
# # #   3. Write the M2M link directly:
# # #        message.write({'attachment_ids': [(4, att_id), ...]})
# # #      This is exactly what Odoo's own _message_post_process_attachments does
# # #      internally — we just do it after message creation to avoid the filter.
# # # """

# # # import base64
# # # import binascii
# # # import json
# # # import logging
# # # import mimetypes
# # # from html.parser import HTMLParser

# # # from markupsafe import Markup, escape
# # # from werkzeug.utils import secure_filename

# # # from odoo import http
# # # from odoo.http import Response, request

# # # _logger = logging.getLogger(__name__)


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # # HTML → plain-text stripper
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # class _HTMLStripper(HTMLParser):
# # #     def __init__(self):
# # #         super().__init__()
# # #         self._parts = []

# # #     def handle_data(self, data):
# # #         self._parts.append(data)

# # #     def get_text(self):
# # #         return ' '.join(self._parts).strip()


# # # def _strip_html(html):
# # #     if not html:
# # #         return ''
# # #     stripper = _HTMLStripper()
# # #     try:
# # #         stripper.feed(html)
# # #         return stripper.get_text()
# # #     except Exception:
# # #         return html


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # # Author-type resolver
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # def _resolve_author_type(partner):
# # #     if not partner:
# # #         return 'public'
# # #     users = partner.user_ids
# # #     if not users:
# # #         return 'public'
# # #     for user in users:
# # #         if not user.share:
# # #             return 'internal_user'
# # #     return 'portal_user'


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # # Message serialiser
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # def _serialise_message(msg, ticket):
# # #     partner     = msg.author_id
# # #     author_type = _resolve_author_type(partner)

# # #     assigned_pid = (
# # #         ticket.user_id.partner_id.id
# # #         if ticket.user_id and ticket.user_id.partner_id
# # #         else False
# # #     )

# # #     if author_type in ('portal_user', 'public'):
# # #         direction = 'inbound'
# # #     elif assigned_pid and partner and partner.id == assigned_pid:
# # #         direction = 'outbound'
# # #     else:
# # #         direction = 'internal'

# # #     subtype     = msg.subtype_id
# # #     mt_note_ref = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # #     is_internal_note = bool(
# # #         subtype and mt_note_ref and subtype.id == mt_note_ref.id
# # #     )

# # #     return {
# # #         'message_id':       msg.id,
# # #         'parent_id':        msg.parent_id.id if msg.parent_id else None,
# # #         'body_html':        msg.body or '',
# # #         'body_text':        _strip_html(msg.body),
# # #         'message_type':     msg.message_type or '',
# # #         'subtype_name':     subtype.name if subtype else None,
# # #         'is_internal_note': is_internal_note,
# # #         'direction':        direction,
# # #         'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
# # #         'attachments':      [
# # #             {
# # #                 'id':       att.id,
# # #                 'name':     att.name,
# # #                 'mimetype': att.mimetype,
# # #                 'url':      '/web/content/%s?download=true' % att.id,
# # #             }
# # #             for att in msg.attachment_ids
# # #         ],
# # #         'author': {
# # #             'id':                partner.id if partner else None,
# # #             'name':              partner.name if partner else 'Unknown',
# # #             'email':             partner.email if partner else None,
# # #             'user_type':         author_type,
# # #             'is_assigned_agent': bool(
# # #                 assigned_pid and partner and partner.id == assigned_pid
# # #             ),
# # #         },
# # #         'reply_count': 0,
# # #         'replies':     [],
# # #     }


# # # def _normalise_orphan_parent_ids(flat_messages):
# # #     message_ids = {msg['message_id'] for msg in flat_messages}
# # #     for msg in flat_messages:
# # #         if msg['parent_id'] and msg['parent_id'] not in message_ids:
# # #             msg['parent_id'] = None
# # #     return flat_messages


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # # Tree / hybrid builders (unchanged)
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # def _build_tree(flat_messages):
# # #     index = {m['message_id']: m for m in flat_messages}
# # #     roots = []
# # #     for msg in flat_messages:
# # #         pid = msg['parent_id']
# # #         if pid and pid in index:
# # #             parent = index[pid]
# # #             parent['replies'].append(msg)
# # #             parent['reply_count'] += 1
# # #         else:
# # #             roots.append(msg)

# # #     def _sort_level(nodes):
# # #         nodes.sort(key=lambda m: m['date'] or '')
# # #         for node in nodes:
# # #             if node['replies']:
# # #                 _sort_level(node['replies'])

# # #     _sort_level(roots)
# # #     return roots


# # # def _build_hybrid(flat_messages):
# # #     mid_set      = {m['message_id'] for m in flat_messages}
# # #     children_map = {}
# # #     roots        = []

# # #     for msg in flat_messages:
# # #         pid = msg['parent_id']
# # #         if pid and pid in mid_set:
# # #             children_map.setdefault(pid, []).append(msg)
# # #         else:
# # #             roots.append(msg)

# # #     roots.sort(key=lambda m: m['date'] or '')
# # #     for kids in children_map.values():
# # #         kids.sort(key=lambda m: m['date'] or '')

# # #     timeline = []

# # #     def _dfs(msg, depth, thread_root_id):
# # #         entry = {k: v for k, v in msg.items() if k != 'replies'}
# # #         entry['depth']          = depth
# # #         entry['thread_root_id'] = thread_root_id
# # #         timeline.append(entry)
# # #         for child in children_map.get(msg['message_id'], []):
# # #             _dfs(child, depth + 1, thread_root_id)

# # #     for root in roots:
# # #         _dfs(root, 0, root['message_id'])

# # #     return timeline


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # # Controller
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # class HelpdeskConversationController(http.Controller):

# # #     MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# # #     # =========================================================================
# # #     # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
# # #     # =========================================================================

# # #     @http.route(
# # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
# # #         type='http',
# # #         auth='public',
# # #         methods=['GET'],
# # #         csrf=False,
# # #         save_session=False,
# # #     )
# # #     def get_conversation(self, ticket_id, **query_params):
# # #         mode             = query_params.get('mode', 'tree').strip().lower()
# # #         include_internal = query_params.get('include_internal', '1') != '0'
# # #         include_system   = query_params.get('include_system',   '0') == '1'

# # #         if mode not in ('tree', 'flat', 'hybrid'):
# # #             return self._json_response(
# # #                 {"status": "error",
# # #                  "message": "Invalid mode '%s'. Accepted: tree, flat, hybrid." % mode},
# # #                 status=400,
# # #             )

# # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # #         if not ticket.exists():
# # #             return self._json_response(
# # #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# # #                 status=404,
# # #             )

# # #         allowed_types = ['comment', 'email']
# # #         if include_system:
# # #             allowed_types += ['notification', 'user_notification']

# # #         domain = [
# # #             ('model',        '=',  'helpdesk.ticket'),
# # #             ('res_id',       '=',  ticket_id),
# # #             ('message_type', 'in', allowed_types),
# # #         ]

# # #         if not include_internal:
# # #             mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
# # #             if mt_note:
# # #                 domain.append(('subtype_id', '!=', mt_note.id))

# # #         try:
# # #             messages = request.env['mail.message'].sudo().search(
# # #                 domain, order='date asc',
# # #             )
# # #         except Exception as exc:
# # #             _logger.error(
# # #                 "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
# # #                 ticket_id, exc,
# # #             )
# # #             return self._json_response(
# # #                 {"status": "error", "message": "Failed to retrieve conversation."},
# # #                 status=500,
# # #             )

# # #         flat_list = _normalise_orphan_parent_ids(
# # #             [_serialise_message(msg, ticket) for msg in messages]
# # #         )

# # #         if mode == 'tree':
# # #             conversation = _build_tree(flat_list)
# # #         elif mode == 'hybrid':
# # #             conversation = _build_hybrid(flat_list)
# # #         else:
# # #             conversation = flat_list

# # #         assigned_agent = None
# # #         if ticket.user_id:
# # #             assigned_agent = {
# # #                 'id':    ticket.user_id.id,
# # #                 'name':  ticket.user_id.name,
# # #                 'email': ticket.user_id.email,
# # #             }

# # #         return self._json_response({
# # #             'status':         'success',
# # #             'ticket_id':      ticket.id,
# # #             'ticket_name':    ticket.name or '',
# # #             'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
# # #             'assigned_agent': assigned_agent,
# # #             'total_messages': len(flat_list),
# # #             'mode':           mode,
# # #             'conversation':   conversation,
# # #         })

# # #     # =========================================================================
# # #     # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# # #     # =========================================================================

# # #     @http.route(
# # #         '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
# # #         type='http',
# # #         auth='public',
# # #         methods=['POST'],
# # #         csrf=False,
# # #         save_session=False,
# # #     )
# # #     def inbound_message(self, ticket_id, **_kwargs):
# # #         """
# # #         Receive an inbound message from the external portal.

# # #         Request body (JSON):
# # #           {
# # #             "sender_name":       "John Doe",
# # #             "sender_email":      "john@example.com",
# # #             "body":              "Hello, I need help.",
# # #             "parent_message_id": null,
# # #             "attachments": [
# # #               {
# # #                 "filename": "screenshot.png",
# # #                 "data":     "<base64-encoded bytes>",
# # #                 "mimetype": "image/png"
# # #               }
# # #             ]
# # #           }

# # #         Multipart/form-data is also accepted; files go in 'file',
# # #         'files', or 'attachments_file' fields.

# # #         Attachment flow (Odoo 19 compatible)
# # #         ──────────────────────────────────────
# # #         We deliberately do NOT pass attachment_ids or attachments= to
# # #         message_post because _message_post_process_attachments filters
# # #         out any ir.attachment whose res_model is already set.

# # #         Instead:
# # #           1. Post the message (text body only).
# # #           2. Create ir.attachment records with sudo(), linked to the
# # #              ticket (res_model='helpdesk.ticket', res_id=ticket.id) so
# # #              they appear in the ticket's Files section.
# # #           3. Write the M2M link directly on the message record:
# # #                message.write({'attachment_ids': [(4, att_id), ...]})
# # #              This is exactly what Odoo's internal code does — we just
# # #              do it after message creation to avoid the filter.

# # #         Success (200):
# # #           { "status": "success", "message_id": 45, "ticket_id": 12,
# # #             "attachment_ids": [67, 68] }

# # #         Errors: 400 | 404 | 422 | 500
# # #         """
# # #         # ── Parse request body ───────────────────────────────────────────────
# # #         try:
# # #             payload, uploaded_files = self._parse_inbound_payload()
# # #         except ValueError as exc:
# # #             return self._json_response(
# # #                 {"status": "error", "message": str(exc)}, status=400,
# # #             )

# # #         sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
# # #         sender_email    = str(payload.get('sender_email', '')).strip()
# # #         body            = str(payload.get('body',         '')).strip()
# # #         raw_parent      = payload.get('parent_message_id')
# # #         raw_attachments = payload.get('attachments') or []

# # #         if not body and not raw_attachments and not uploaded_files:
# # #             return self._json_response(
# # #                 {"status": "error",
# # #                  "message": "'body' or 'attachments' is required."},
# # #                 status=422,
# # #             )

# # #         # ── Fetch ticket ─────────────────────────────────────────────────────
# # #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# # #         if not ticket.exists():
# # #             return self._json_response(
# # #                 {"status": "error",
# # #                  "message": "Ticket #%s not found." % ticket_id},
# # #                 status=404,
# # #             )

# # #         # ── Resolve author partner ───────────────────────────────────────────
# # #         author_id = False
# # #         if sender_email:
# # #             Partner = request.env['res.partner'].sudo()
# # #             partner = Partner.search([('email', '=', sender_email)], limit=1)
# # #             if not partner:
# # #                 partner = Partner.create({
# # #                     'name':  sender_name or sender_email,
# # #                     'email': sender_email,
# # #                 })
# # #             author_id = partner.id

# # #         # ── Resolve optional parent_message_id ──────────────────────────────
# # #         parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

# # #         # ── Validate & decode attachment data BEFORE any DB write ────────────
# # #         # Both helpers return (filename, bytes, mimetype) tuples.
# # #         # Size and base64 integrity are checked here so we can return 422
# # #         # without having touched the DB yet.
# # #         try:
# # #             attachment_tuples  = self._prepare_inbound_attachments(raw_attachments)
# # #             attachment_tuples += self._prepare_uploaded_attachments(uploaded_files)
# # #         except ValueError as exc:
# # #             return self._json_response(
# # #                 {"status": "error", "message": str(exc)}, status=422,
# # #             )
# # #         except Exception as exc:
# # #             _logger.error(
# # #                 "[Zencore] Unexpected error processing attachments "
# # #                 "for ticket_id=%s: %s", ticket_id, exc,
# # #             )
# # #             return self._json_response(
# # #                 {"status": "error", "message": "Failed to process attachments."},
# # #                 status=500,
# # #             )

# # #         # ── Step 1: Post message (body only, no attachments yet) ─────────────
# # #         chatter_body = Markup("<p>%s</p>" % escape(body or ""))

# # #         try:
# # #             message = ticket.message_post(
# # #                 body=chatter_body,
# # #                 author_id=author_id or False,
# # #                 message_type='comment',
# # #                 subtype_xmlid='mail.mt_note',
# # #                 parent_id=parent_id or False,
# # #             )
# # #         except Exception as exc:
# # #             _logger.error(
# # #                 "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
# # #                 ticket_id, exc,
# # #             )
# # #             return self._json_response(
# # #                 {"status": "error", "message": "Failed to post message."},
# # #                 status=500,
# # #             )

# # #         # ── Step 2 + 3: Create ir.attachment records, then link to message ───
# # #         # WHY post-message:
# # #         #   message_post(attachment_ids=[...]) passes IDs through
# # #         #   _message_post_process_attachments which FILTERS OUT attachments
# # #         #   whose res_model is already set (anything other than
# # #         #   'mail.compose.message').  Creating after avoids that filter
# # #         #   entirely and lets us write the M2M directly.
# # #         #
# # #         # WHY res_model='helpdesk.ticket':
# # #         #   Matches what Odoo sets internally when you use
# # #         #   message_post(attachments=[(name, bytes)]).  Ensures the file
# # #         #   appears in the ticket's Attachments tab as well as in the
# # #         #   message bubble.
# # #         attachment_ids = self._create_and_link_attachments(
# # #             ticket, message, attachment_tuples
# # #         )

# # #         # ── Notify assigned agent ────────────────────────────────────────────
# # #         ticket._notify_assigned_user_on_inbound()

# # #         return self._json_response({
# # #             "status":         "success",
# # #             "message_id":     message.id,
# # #             "ticket_id":      ticket.id,
# # #             "attachment_ids": attachment_ids,
# # #         })

# # #     # ─────────────────────────────────────────────────────────────────────────
# # #     # Attachment helpers
# # #     # ─────────────────────────────────────────────────────────────────────────

# # #     @staticmethod
# # #     def _prepare_inbound_attachments(raw_attachments):
# # #         """
# # #         Decode and validate base64 attachments from a JSON payload.

# # #         Returns a list of (filename, file_bytes, mimetype) tuples.
# # #         Raises ValueError on the first invalid entry.
# # #         """
# # #         if not isinstance(raw_attachments, list):
# # #             raise ValueError("'attachments' must be a list.")

# # #         result = []
# # #         for index, item in enumerate(raw_attachments, start=1):
# # #             if not isinstance(item, dict):
# # #                 raise ValueError("Attachment #%s must be an object." % index)

# # #             filename = HelpdeskConversationController._clean_filename(
# # #                 item.get('filename') or item.get('name') or 'attachment-%s' % index
# # #             )
# # #             raw_data = item.get('data') or item.get('datas') or item.get('content')
# # #             if not raw_data:
# # #                 raise ValueError(
# # #                     "Attachment '%s' is missing base64 data." % filename
# # #                 )

# # #             raw_data = str(raw_data).strip()
# # #             # Strip data-URI prefix:  "data:image/png;base64,<data>"
# # #             if ',' in raw_data and raw_data.lower().startswith('data:'):
# # #                 raw_data = raw_data.split(',', 1)[1]

# # #             try:
# # #                 file_content = base64.b64decode(raw_data, validate=True)
# # #             except (binascii.Error, ValueError):
# # #                 raise ValueError(
# # #                     "Attachment '%s' has invalid base64 data." % filename
# # #                 )

# # #             HelpdeskConversationController._check_attachment_size(
# # #                 filename, file_content
# # #             )

# # #             mimetype = (
# # #                 item.get('mimetype')
# # #                 or mimetypes.guess_type(filename)[0]
# # #                 or 'application/octet-stream'
# # #             )
# # #             result.append((filename, file_content, mimetype))
# # #         return result

# # #     @staticmethod
# # #     def _prepare_uploaded_attachments(uploaded_files):
# # #         """
# # #         Read and validate files from a multipart/form-data upload.

# # #         Returns a list of (filename, file_bytes, mimetype) tuples.
# # #         """
# # #         result = []
# # #         for uploaded_file in uploaded_files:
# # #             if not uploaded_file or not uploaded_file.filename:
# # #                 continue
# # #             filename     = HelpdeskConversationController._clean_filename(
# # #                 uploaded_file.filename
# # #             )
# # #             file_content = uploaded_file.read()
# # #             HelpdeskConversationController._check_attachment_size(
# # #                 filename, file_content
# # #             )
# # #             mimetype = (
# # #                 uploaded_file.mimetype
# # #                 or mimetypes.guess_type(filename)[0]
# # #                 or 'application/octet-stream'
# # #             )
# # #             result.append((filename, file_content, mimetype))
# # #         return result

# # #     @staticmethod
# # #     def _create_and_link_attachments(ticket, message, attachment_tuples):
# # #         """
# # #         Create ir.attachment records and link them to both the ticket and
# # #         the chatter message.

# # #         Two things happen here:
# # #           A) ir.attachment is created with:
# # #                res_model = 'helpdesk.ticket'
# # #                res_id    = ticket.id
# # #              → file appears in the ticket's Attachments tab.

# # #           B) M2M link is written directly on the mail.message record:
# # #                message.write({'attachment_ids': [(4, att_id), ...]})
# # #              → file appears inside the chatter message bubble.

# # #         This two-step pattern bypasses _message_post_process_attachments
# # #         which would silently drop our attachments because their res_model
# # #         is already set (Odoo 19 filter behaviour).

# # #         Returns a list of ir.attachment IDs (empty list when no files).
# # #         """
# # #         if not attachment_tuples:
# # #             return []

# # #         att_ids = []
# # #         for filename, file_content, mimetype in attachment_tuples:
# # #             att = request.env['ir.attachment'].sudo().create({
# # #                 'name':      filename,
# # #                 'type':      'binary',
# # #                 'datas':     base64.b64encode(file_content),
# # #                 'mimetype':  mimetype,
# # #                 'res_model': 'helpdesk.ticket',   # ticket's Files tab
# # #                 'res_id':    ticket.id,
# # #             })
# # #             att_ids.append(att.id)
# # #             _logger.debug(
# # #                 "[Zencore] Created attachment id=%s name='%s' ticket_id=%s",
# # #                 att.id, filename, ticket.id,
# # #             )

# # #         if att_ids:
# # #             # Write M2M so files appear inside the message bubble.
# # #             # (4, id) = "add link" ORM command for Many2many.
# # #             message.sudo().write({
# # #                 'attachment_ids': [(4, att_id) for att_id in att_ids],
# # #             })
# # #             _logger.debug(
# # #                 "[Zencore] Linked %s attachment(s) to message_id=%s",
# # #                 len(att_ids), message.id,
# # #             )

# # #         return att_ids

# # #     # ─────────────────────────────────────────────────────────────────────────
# # #     # Shared private helpers (unchanged)
# # #     # ─────────────────────────────────────────────────────────────────────────

# # #     def _parse_inbound_payload(self):
# # #         """Support JSON base64 attachments and multipart/form-data file uploads."""
# # #         content_type = (request.httprequest.content_type or '').lower()
# # #         if content_type.startswith('multipart/form-data'):
# # #             payload = dict(request.httprequest.form.items())
# # #             attachments = payload.get('attachments')
# # #             if attachments:
# # #                 try:
# # #                     payload['attachments'] = json.loads(attachments)
# # #                 except (TypeError, ValueError):
# # #                     raise ValueError(
# # #                         "'attachments' must be valid JSON when sent as form-data."
# # #                     )
# # #             uploaded_files = []
# # #             for field_name in ('file', 'files', 'attachments_file'):
# # #                 uploaded_files.extend(
# # #                     request.httprequest.files.getlist(field_name)
# # #                 )
# # #             return payload, uploaded_files

# # #         raw = request.httprequest.data
# # #         if not raw:
# # #             raise ValueError('Empty request body.')
# # #         try:
# # #             return json.loads(raw), []
# # #         except (ValueError, TypeError) as exc:
# # #             _logger.warning(
# # #                 "[Zencore] Malformed JSON in inbound_message: %s", exc
# # #             )
# # #             raise ValueError('Invalid JSON payload.')

# # #     @staticmethod
# # #     def _check_attachment_size(filename, file_content):
# # #         if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
# # #             raise ValueError(
# # #                 "Attachment '%s' exceeds 10MB limit." % filename
# # #             )

# # #     @staticmethod
# # #     def _clean_filename(filename):
# # #         filename = secure_filename(str(filename or '').strip())
# # #         return filename or 'attachment'

# # #     @staticmethod
# # #     def _json_response(data, status=200):
# # #         return Response(
# # #             json.dumps(data, default=str),
# # #             content_type='application/json; charset=utf-8',
# # #             status=status,
# # #         )

# # #     @staticmethod
# # #     def _resolve_parent_message_id(raw_parent, ticket_id):
# # #         """Validate and resolve parent_message_id. Returns int id or False."""
# # #         if raw_parent is None:
# # #             return False

# # #         try:
# # #             parent_int = int(raw_parent)
# # #         except (ValueError, TypeError):
# # #             _logger.warning(
# # #                 "[Zencore] parent_message_id='%s' is not an integer "
# # #                 "(ticket_id=%s). Ignoring.",
# # #                 raw_parent, ticket_id,
# # #             )
# # #             return False

# # #         parent_msg = request.env['mail.message'].sudo().browse(parent_int)
# # #         if not parent_msg.exists():
# # #             _logger.warning(
# # #                 "[Zencore] parent_message_id=%s does not exist "
# # #                 "(ticket_id=%s). Ignoring.",
# # #                 parent_int, ticket_id,
# # #             )
# # #             return False

# # #         if (
# # #             parent_msg.model != 'helpdesk.ticket'
# # #             or parent_msg.res_id != ticket_id
# # #         ):
# # #             _logger.warning(
# # #                 "[Zencore] parent_message_id=%s does not belong to "
# # #                 "ticket_id=%s. Ignoring.",
# # #                 parent_int, ticket_id,
# # #             )
# # #             return False

# # #         return parent_msg.id

# # """
# # zencore_helpdesk_conversion_api — controllers/main.py

# # Endpoints
# # ─────────
# #   POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# #   GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation

# # Auth: public on all routes.

# # Attachment design (Odoo 19)
# # ───────────────────────────
# # message_post(attachment_ids=[...]) passes IDs through
# # _message_post_process_attachments which silently drops any attachment
# # whose res_model is already set to something other than
# # 'mail.compose.message'.

# # Correct pattern:
# #   1. Post the message (body only, no attachments).
# #   2. Create ir.attachment with res_model='helpdesk.ticket', res_id=ticket.id
# #      so the files appear in the ticket's Attachments tab.
# #   3. Write the M2M link directly:
# #        message.write({'attachment_ids': [(4, att_id), ...]})
# #      This is exactly what Odoo's own _message_post_process_attachments does
# #      internally — we just do it after message creation to avoid the filter.
# # """

# # import base64
# # import binascii
# # import json
# # import logging
# # import mimetypes
# # from html.parser import HTMLParser

# # from markupsafe import Markup, escape
# # from werkzeug.utils import secure_filename

# # from odoo import http
# # from odoo.http import Response, request

# # _logger = logging.getLogger(__name__)


# # # ─────────────────────────────────────────────────────────────────────────────
# # # HTML → plain-text stripper
# # # ─────────────────────────────────────────────────────────────────────────────

# # class _HTMLStripper(HTMLParser):
# #     def __init__(self):
# #         super().__init__()
# #         self._parts = []

# #     def handle_data(self, data):
# #         self._parts.append(data)

# #     def get_text(self):
# #         return ' '.join(self._parts).strip()


# # def _strip_html(html):
# #     if not html:
# #         return ''
# #     stripper = _HTMLStripper()
# #     try:
# #         stripper.feed(html)
# #         return stripper.get_text()
# #     except Exception:
# #         return html


# # # ─────────────────────────────────────────────────────────────────────────────
# # # Author-type resolver
# # # ─────────────────────────────────────────────────────────────────────────────

# # def _resolve_author_type(partner):
# #     if not partner:
# #         return 'public'
# #     users = partner.user_ids
# #     if not users:
# #         return 'public'
# #     for user in users:
# #         if not user.share:
# #             return 'internal_user'
# #     return 'portal_user'


# # # ─────────────────────────────────────────────────────────────────────────────
# # # Message serialiser
# # # ─────────────────────────────────────────────────────────────────────────────

# # def _serialise_message(msg, ticket):
# #     partner     = msg.author_id
# #     author_type = _resolve_author_type(partner)

# #     assigned_pid = (
# #         ticket.user_id.partner_id.id
# #         if ticket.user_id and ticket.user_id.partner_id
# #         else False
# #     )

# #     if author_type in ('portal_user', 'public'):
# #         direction = 'inbound'
# #     elif assigned_pid and partner and partner.id == assigned_pid:
# #         direction = 'outbound'
# #     else:
# #         direction = 'internal'

# #     subtype     = msg.subtype_id
# #     mt_note_ref = request.env.ref('mail.mt_note', raise_if_not_found=False)
# #     is_internal_note = bool(
# #         subtype and mt_note_ref and subtype.id == mt_note_ref.id
# #     )

# #     return {
# #         'message_id':       msg.id,
# #         'parent_id':        msg.parent_id.id if msg.parent_id else None,
# #         'body_html':        msg.body or '',
# #         'body_text':        _strip_html(msg.body),
# #         'message_type':     msg.message_type or '',
# #         'subtype_name':     subtype.name if subtype else None,
# #         'is_internal_note': is_internal_note,
# #         'direction':        direction,
# #         'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
# #         'attachments':      [
# #             {
# #                 'id':       att.id,
# #                 'name':     att.name,
# #                 'mimetype': att.mimetype,
# #                 'url':      '/web/content/%s?download=true' % att.id,
# #             }
# #             for att in msg.attachment_ids
# #         ],
# #         'author': {
# #             'id':                partner.id if partner else None,
# #             'name':              partner.name if partner else 'Unknown',
# #             'email':             partner.email if partner else None,
# #             'user_type':         author_type,
# #             'is_assigned_agent': bool(
# #                 assigned_pid and partner and partner.id == assigned_pid
# #             ),
# #         },
# #         'reply_count': 0,
# #         'replies':     [],
# #     }


# # def _normalise_orphan_parent_ids(flat_messages):
# #     message_ids = {msg['message_id'] for msg in flat_messages}
# #     for msg in flat_messages:
# #         if msg['parent_id'] and msg['parent_id'] not in message_ids:
# #             msg['parent_id'] = None
# #     return flat_messages


# # # ─────────────────────────────────────────────────────────────────────────────
# # # Tree / hybrid builders
# # # ─────────────────────────────────────────────────────────────────────────────

# # def _build_tree(flat_messages):
# #     index = {m['message_id']: m for m in flat_messages}
# #     roots = []
# #     for msg in flat_messages:
# #         pid = msg['parent_id']
# #         if pid and pid in index:
# #             parent = index[pid]
# #             parent['replies'].append(msg)
# #             parent['reply_count'] += 1
# #         else:
# #             roots.append(msg)

# #     def _sort_level(nodes):
# #         nodes.sort(key=lambda m: m['date'] or '')
# #         for node in nodes:
# #             if node['replies']:
# #                 _sort_level(node['replies'])

# #     _sort_level(roots)
# #     return roots


# # def _build_hybrid(flat_messages):
# #     mid_set      = {m['message_id'] for m in flat_messages}
# #     children_map = {}
# #     roots        = []

# #     for msg in flat_messages:
# #         pid = msg['parent_id']
# #         if pid and pid in mid_set:
# #             children_map.setdefault(pid, []).append(msg)
# #         else:
# #             roots.append(msg)

# #     roots.sort(key=lambda m: m['date'] or '')
# #     for kids in children_map.values():
# #         kids.sort(key=lambda m: m['date'] or '')

# #     timeline = []

# #     def _dfs(msg, depth, thread_root_id):
# #         entry = {k: v for k, v in msg.items() if k != 'replies'}
# #         entry['depth']          = depth
# #         entry['thread_root_id'] = thread_root_id
# #         timeline.append(entry)
# #         for child in children_map.get(msg['message_id'], []):
# #             _dfs(child, depth + 1, thread_root_id)

# #     for root in roots:
# #         _dfs(root, 0, root['message_id'])

# #     return timeline


# # # ─────────────────────────────────────────────────────────────────────────────
# # # Controller
# # # ─────────────────────────────────────────────────────────────────────────────

# # class HelpdeskConversationController(http.Controller):

# #     MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# #     # =========================================================================
# #     # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
# #     # =========================================================================

# #     @http.route(
# #         '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
# #         type='http',
# #         auth='public',
# #         methods=['GET'],
# #         csrf=False,
# #         save_session=False,
# #     )
# #     def get_conversation(self, ticket_id, **query_params):
# #         mode             = query_params.get('mode', 'tree').strip().lower()
# #         include_internal = query_params.get('include_internal', '1') != '0'
# #         include_system   = query_params.get('include_system',   '0') == '1'

# #         if mode not in ('tree', 'flat', 'hybrid'):
# #             return self._json_response(
# #                 {"status": "error",
# #                  "message": "Invalid mode '%s'. Accepted: tree, flat, hybrid." % mode},
# #                 status=400,
# #             )

# #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# #         if not ticket.exists():
# #             return self._json_response(
# #                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
# #                 status=404,
# #             )

# #         allowed_types = ['comment', 'email']
# #         if include_system:
# #             allowed_types += ['notification', 'user_notification']

# #         domain = [
# #             ('model',        '=',  'helpdesk.ticket'),
# #             ('res_id',       '=',  ticket_id),
# #             ('message_type', 'in', allowed_types),
# #         ]

# #         if not include_internal:
# #             mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
# #             if mt_note:
# #                 domain.append(('subtype_id', '!=', mt_note.id))

# #         try:
# #             messages = request.env['mail.message'].sudo().search(
# #                 domain, order='date asc',
# #             )
# #         except Exception as exc:
# #             _logger.error(
# #                 "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
# #                 ticket_id, exc,
# #             )
# #             return self._json_response(
# #                 {"status": "error", "message": "Failed to retrieve conversation."},
# #                 status=500,
# #             )

# #         flat_list = _normalise_orphan_parent_ids(
# #             [_serialise_message(msg, ticket) for msg in messages]
# #         )

# #         if mode == 'tree':
# #             conversation = _build_tree(flat_list)
# #         elif mode == 'hybrid':
# #             conversation = _build_hybrid(flat_list)
# #         else:
# #             conversation = flat_list

# #         assigned_agent = None
# #         if ticket.user_id:
# #             assigned_agent = {
# #                 'id':    ticket.user_id.id,
# #                 'name':  ticket.user_id.name,
# #                 'email': ticket.user_id.email,
# #             }

# #         return self._json_response({
# #             'status':         'success',
# #             'ticket_id':      ticket.id,
# #             'ticket_name':    ticket.name or '',
# #             'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
# #             'assigned_agent': assigned_agent,
# #             'total_messages': len(flat_list),
# #             'mode':           mode,
# #             'conversation':   conversation,
# #         })

# #     # =========================================================================
# #     # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
# #     # =========================================================================

# #     @http.route(
# #         '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
# #         type='http',
# #         auth='public',
# #         methods=['POST'],
# #         csrf=False,
# #         save_session=False,
# #     )
# #     def inbound_message(self, ticket_id, **_kwargs):
# #         # ── Parse request body ───────────────────────────────────────────────
# #         try:
# #             payload, uploaded_files = self._parse_inbound_payload()
# #         except ValueError as exc:
# #             return self._json_response(
# #                 {"status": "error", "message": str(exc)}, status=400,
# #             )

# #         sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
# #         sender_email    = str(payload.get('sender_email', '')).strip()
# #         body            = str(payload.get('body',         '')).strip()
# #         raw_parent      = payload.get('parent_message_id')
# #         raw_attachments = payload.get('attachments') or []

# #         if not body and not raw_attachments and not uploaded_files:
# #             return self._json_response(
# #                 {"status": "error",
# #                  "message": "'body' or 'attachments' is required."},
# #                 status=422,
# #             )

# #         # ── Fetch ticket ─────────────────────────────────────────────────────
# #         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
# #         if not ticket.exists():
# #             return self._json_response(
# #                 {"status": "error",
# #                  "message": "Ticket #%s not found." % ticket_id},
# #                 status=404,
# #             )

# #         # ── Resolve author partner ───────────────────────────────────────────
# #         author_id = False
# #         if sender_email:
# #             Partner = request.env['res.partner'].sudo()
# #             partner = Partner.search([('email', '=', sender_email)], limit=1)
# #             if not partner:
# #                 partner = Partner.create({
# #                     'name':  sender_name or sender_email,
# #                     'email': sender_email,
# #                 })
# #             author_id = partner.id

# #         # ── Resolve optional parent_message_id ──────────────────────────────
# #         parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

# #         # ── Validate & decode attachment data BEFORE any DB write ────────────
# #         try:
# #             attachment_tuples  = self._prepare_inbound_attachments(raw_attachments)
# #             attachment_tuples += self._prepare_uploaded_attachments(uploaded_files)
# #         except ValueError as exc:
# #             return self._json_response(
# #                 {"status": "error", "message": str(exc)}, status=422,
# #             )
# #         except Exception as exc:
# #             _logger.error(
# #                 "[Zencore] Unexpected error processing attachments "
# #                 "for ticket_id=%s: %s", ticket_id, exc,
# #             )
# #             return self._json_response(
# #                 {"status": "error", "message": "Failed to process attachments."},
# #                 status=500,
# #             )

# #         # ── Step 1: Post message (body only, no attachments yet) ─────────────
# #         chatter_body = Markup("<p>%s</p>" % escape(body or ""))

# #         try:
# #             message = ticket.message_post(
# #                 body=chatter_body,
# #                 author_id=author_id or False,
# #                 message_type='comment',
# #                 subtype_xmlid='mail.mt_note',
# #                 parent_id=parent_id or False,
# #             )
# #         except Exception as exc:
# #             _logger.error(
# #                 "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
# #                 ticket_id, exc,
# #             )
# #             return self._json_response(
# #                 {"status": "error", "message": "Failed to post message."},
# #                 status=500,
# #             )

# #         # ── Step 2 + 3: Create ir.attachment records, then link to message ───
# #         attachment_ids = self._create_and_link_attachments(
# #             ticket, message, attachment_tuples
# #         )

# #         # ── Notify assigned agent ────────────────────────────────────────────
# #         ticket._notify_assigned_user_on_inbound()

# #         return self._json_response({
# #             "status":         "success",
# #             "message_id":     message.id,
# #             "ticket_id":      ticket.id,
# #             "attachment_ids": attachment_ids,
# #         })

# #     # ─────────────────────────────────────────────────────────────────────────
# #     # Attachment helpers
# #     # ─────────────────────────────────────────────────────────────────────────

# #     @staticmethod
# #     def _prepare_inbound_attachments(raw_attachments):
# #         """
# #         Decode and validate base64 attachments from a JSON payload.
# #         Returns a list of (filename, file_bytes, mimetype) tuples.
# #         Raises ValueError on the first invalid entry.
# #         """
# #         if not isinstance(raw_attachments, list):
# #             raise ValueError("'attachments' must be a list.")

# #         result = []
# #         for index, item in enumerate(raw_attachments, start=1):
# #             if not isinstance(item, dict):
# #                 raise ValueError("Attachment #%s must be an object." % index)

# #             filename = HelpdeskConversationController._clean_filename(
# #                 item.get('filename') or item.get('name') or 'attachment-%s' % index
# #             )
# #             raw_data = item.get('data') or item.get('datas') or item.get('content')
# #             if not raw_data:
# #                 raise ValueError(
# #                     "Attachment '%s' is missing base64 data." % filename
# #                 )

# #             raw_data = str(raw_data).strip()
# #             # Strip data-URI prefix: "data:image/png;base64,<data>"
# #             if ',' in raw_data and raw_data.lower().startswith('data:'):
# #                 raw_data = raw_data.split(',', 1)[1]

# #             try:
# #                 file_content = base64.b64decode(raw_data, validate=True)
# #             except (binascii.Error, ValueError):
# #                 raise ValueError(
# #                     "Attachment '%s' has invalid base64 data." % filename
# #                 )

# #             HelpdeskConversationController._check_attachment_size(
# #                 filename, file_content
# #             )

# #             mimetype = (
# #                 item.get('mimetype')
# #                 or mimetypes.guess_type(filename)[0]
# #                 or 'application/octet-stream'
# #             )
# #             result.append((filename, file_content, mimetype))
# #         return result

# #     @staticmethod
# #     def _prepare_uploaded_attachments(uploaded_files):
# #         """
# #         Read and validate files from a multipart/form-data upload.

# #         FIX 1 — stream.seek(0): Werkzeug may have partially consumed the
# #         stream during request parsing.  Always reset before reading so that
# #         file_content is never silently empty.

# #         Returns a list of (filename, file_bytes, mimetype) tuples.
# #         Skips files with no name or zero-byte content (with a warning).
# #         """
# #         result = []
# #         for uploaded_file in uploaded_files:
# #             if not uploaded_file or not uploaded_file.filename:
# #                 continue

# #             filename = HelpdeskConversationController._clean_filename(
# #                 uploaded_file.filename
# #             )

# #             # FIX 1: reset stream position before reading
# #             try:
# #                 uploaded_file.stream.seek(0)
# #             except Exception:
# #                 pass  # some stream types don't support seek; best-effort
# #             file_content = uploaded_file.stream.read()

# #             if not file_content:
# #                 _logger.warning(
# #                     "[Zencore] Skipping multipart file '%s': stream yielded "
# #                     "0 bytes (stream may have already been consumed).",
# #                     filename,
# #                 )
# #                 continue

# #             HelpdeskConversationController._check_attachment_size(
# #                 filename, file_content
# #             )

# #             # .mimetype is a Werkzeug FileStorage property; fall back to
# #             # .content_type (older Werkzeug versions) then MIME guessing.
# #             mimetype = (
# #                 getattr(uploaded_file, 'mimetype', None)
# #                 or getattr(uploaded_file, 'content_type', None)
# #                 or mimetypes.guess_type(filename)[0]
# #                 or 'application/octet-stream'
# #             )
# #             result.append((filename, file_content, mimetype))
# #         return result

# #     @staticmethod
# #     def _create_and_link_attachments(ticket, message, attachment_tuples):
# #         """
# #         Create ir.attachment records and link them to both the ticket and
# #         the chatter message.

# #         FIX 2 — datas must be a str, not bytes:
# #           base64.b64encode() returns bytes.  Odoo 19's Binary field writer
# #           (fields.Binary._write) calls base64.b64decode() on whatever is
# #           stored; if it receives bytes it may coerce correctly on some DB
# #           adapters but fails silently or raises on others.  Calling
# #           .decode() makes the value an explicit ASCII string, which is the
# #           format Odoo expects for all Binary/datas fields.

# #         Returns a list of ir.attachment IDs (empty list when no files).
# #         """
# #         if not attachment_tuples:
# #             return []

# #         att_ids = []
# #         for filename, file_content, mimetype in attachment_tuples:
# #             att = request.env['ir.attachment'].sudo().create({
# #                 'name':      filename,
# #                 'type':      'binary',
# #                 # FIX 2: .decode() → str, not bytes
# #                 'datas':     base64.b64encode(file_content).decode(),
# #                 'mimetype':  mimetype,
# #                 'res_model': 'helpdesk.ticket',   # ticket's Files tab
# #                 'res_id':    ticket.id,
# #             })
# #             att_ids.append(att.id)
# #             _logger.debug(
# #                 "[Zencore] Created attachment id=%s name='%s' ticket_id=%s",
# #                 att.id, filename, ticket.id,
# #             )

# #         if att_ids:
# #             # (4, id) = "add link" ORM command for Many2many.
# #             message.sudo().write({
# #                 'attachment_ids': [(4, att_id) for att_id in att_ids],
# #             })
# #             _logger.debug(
# #                 "[Zencore] Linked %s attachment(s) to message_id=%s",
# #                 len(att_ids), message.id,
# #             )

# #         return att_ids

# #     # ─────────────────────────────────────────────────────────────────────────
# #     # Shared private helpers
# #     # ─────────────────────────────────────────────────────────────────────────

# #     def _parse_inbound_payload(self):
# #         """
# #         Support JSON base64 attachments and multipart/form-data file uploads.

# #         FIX 3 — collect ALL uploaded files regardless of field name:
# #           The original code only checked three hard-coded field names
# #           ('file', 'files', 'attachments_file').  Any customer sending
# #           files under a different key (e.g. 'attachment', 'document',
# #           or a portal-generated name) was silently ignored.

# #           request.httprequest.files is a Werkzeug ImmutableMultiDict.
# #           to_dict(flat=False) returns {field_name: [FileStorage, ...]}
# #           for every uploaded file field, so no field name is missed.
# #         """
# #         content_type = (request.httprequest.content_type or '').lower()
# #         if content_type.startswith('multipart/form-data'):
# #             payload = dict(request.httprequest.form.items())

# #             attachments = payload.get('attachments')
# #             if attachments:
# #                 try:
# #                     payload['attachments'] = json.loads(attachments)
# #                 except (TypeError, ValueError):
# #                     raise ValueError(
# #                         "'attachments' must be valid JSON when sent as form-data."
# #                     )

# #             # FIX 3: capture every uploaded file, regardless of field name
# #             uploaded_files = []
# #             for file_list in request.httprequest.files.to_dict(flat=False).values():
# #                 uploaded_files.extend(file_list)

# #             _logger.debug(
# #                 "[Zencore] multipart upload: %d file(s) received across %d field(s)",
# #                 len(uploaded_files),
# #                 len(request.httprequest.files.to_dict(flat=False)),
# #             )
# #             return payload, uploaded_files

# #         raw = request.httprequest.data
# #         if not raw:
# #             raise ValueError('Empty request body.')
# #         try:
# #             return json.loads(raw), []
# #         except (ValueError, TypeError) as exc:
# #             _logger.warning(
# #                 "[Zencore] Malformed JSON in inbound_message: %s", exc
# #             )
# #             raise ValueError('Invalid JSON payload.')

# #     @staticmethod
# #     def _check_attachment_size(filename, file_content):
# #         if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
# #             raise ValueError(
# #                 "Attachment '%s' exceeds 10MB limit." % filename
# #             )

# #     @staticmethod
# #     def _clean_filename(filename):
# #         filename = secure_filename(str(filename or '').strip())
# #         return filename or 'attachment'

# #     @staticmethod
# #     def _json_response(data, status=200):
# #         return Response(
# #             json.dumps(data, default=str),
# #             content_type='application/json; charset=utf-8',
# #             status=status,
# #         )

# #     @staticmethod
# #     def _resolve_parent_message_id(raw_parent, ticket_id):
# #         """Validate and resolve parent_message_id. Returns int id or False."""
# #         if raw_parent is None:
# #             return False

# #         try:
# #             parent_int = int(raw_parent)
# #         except (ValueError, TypeError):
# #             _logger.warning(
# #                 "[Zencore] parent_message_id='%s' is not an integer "
# #                 "(ticket_id=%s). Ignoring.",
# #                 raw_parent, ticket_id,
# #             )
# #             return False

# #         parent_msg = request.env['mail.message'].sudo().browse(parent_int)
# #         if not parent_msg.exists():
# #             _logger.warning(
# #                 "[Zencore] parent_message_id=%s does not exist "
# #                 "(ticket_id=%s). Ignoring.",
# #                 parent_int, ticket_id,
# #             )
# #             return False

# #         if (
# #             parent_msg.model != 'helpdesk.ticket'
# #             or parent_msg.res_id != ticket_id
# #         ):
# #             _logger.warning(
# #                 "[Zencore] parent_message_id=%s does not belong to "
# #                 "ticket_id=%s. Ignoring.",
# #                 parent_int, ticket_id,
# #             )
# #             return False

# #         return parent_msg.id

# """
# zencore_helpdesk_conversion_api — controllers/main.py

# Endpoints
# ─────────
#   POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
#   GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation

# Auth: public on all routes.

# Attachment design (Odoo 19)
# ───────────────────────────
# message_post(attachment_ids=[...]) passes IDs through
# _message_post_process_attachments which silently drops any attachment
# whose res_model is already set to something other than
# 'mail.compose.message'.

# Correct pattern:
#   1. Post the message (body only, no attachments).
#   2. Create ir.attachment with res_model='helpdesk.ticket', res_id=ticket.id
#      so the files appear in the ticket's Attachments tab.
#   3. Write the M2M link directly:
#        message.write({'attachment_ids': [(4, att_id), ...]})
#      This is exactly what Odoo's own _message_post_process_attachments does
#      internally — we just do it after message creation to avoid the filter.

# Attachment READ design (Odoo 19 — GET /conversation)
# ─────────────────────────────────────────────────────
# msg.attachment_ids (ORM Many2many) silently returns [] under auth='public'
# because ir.attachment record rules fire against the public user even when
# the parent mail.message was fetched via sudo().

# Fix: _prefetch_message_attachments() fetches all attachment metadata for
# the full message set in ONE raw SQL JOIN over message_attachment_rel →
# ir_attachment.  This completely bypasses record rules and replaces the
# previous N+1 ORM queries with a single query.
# """

# import base64
# import binascii
# import json
# import logging
# import mimetypes
# from html.parser import HTMLParser

# from markupsafe import Markup, escape
# from werkzeug.utils import secure_filename

# from odoo import http
# from odoo.http import Response, request

# _logger = logging.getLogger(__name__)


# # ─────────────────────────────────────────────────────────────────────────────
# # HTML → plain-text stripper
# # ─────────────────────────────────────────────────────────────────────────────

# class _HTMLStripper(HTMLParser):
#     def __init__(self):
#         super().__init__()
#         self._parts = []

#     def handle_data(self, data):
#         self._parts.append(data)

#     def get_text(self):
#         return ' '.join(self._parts).strip()


# def _strip_html(html):
#     if not html:
#         return ''
#     stripper = _HTMLStripper()
#     try:
#         stripper.feed(html)
#         return stripper.get_text()
#     except Exception:
#         return html


# # ─────────────────────────────────────────────────────────────────────────────
# # Author-type resolver
# # ─────────────────────────────────────────────────────────────────────────────

# def _resolve_author_type(partner):
#     if not partner:
#         return 'public'
#     users = partner.user_ids
#     if not users:
#         return 'public'
#     for user in users:
#         if not user.share:
#             return 'internal_user'
#     return 'portal_user'


# # ─────────────────────────────────────────────────────────────────────────────
# # Attachment prefetch — ONE SQL query for ALL messages
# #
# # WHY raw SQL instead of msg.attachment_ids (ORM field):
# # ────────────────────────────────────────────────────────
# # In Odoo 19, ir.attachment has record rules evaluated at the SQL layer.
# # Even when mail.message is fetched via sudo(), the ORM resolves the
# # attachment_ids Many2many using the *request user's* environment context.
# # Under auth='public' this silently returns [] for every message.
# #
# # A direct JOIN over message_attachment_rel bypasses all record rules and
# # guarantees attachments are returned regardless of request user. This is
# # also the pattern Odoo itself uses in mail.message._message_read().
# # ─────────────────────────────────────────────────────────────────────────────

# def _prefetch_message_attachments(cr, message_ids):
#     """
#     Fetch all attachment metadata for a set of message IDs in ONE SQL query.

#     Returns: { message_id: [ {id, name, mimetype, url}, ... ] }
#     Returns {} immediately when message_ids is empty (safe to call always).
#     """
#     if not message_ids:
#         return {}

#     cr.execute("""
#         SELECT
#             mar.message_id,
#             ia.id           AS att_id,
#             ia.name         AS att_name,
#             ia.mimetype     AS att_mimetype
#         FROM   message_attachment_rel  mar
#         JOIN   ir_attachment           ia  ON ia.id = mar.attachment_id
#         WHERE  mar.message_id = ANY(%s)
#         ORDER  BY mar.message_id, ia.id
#     """, (list(message_ids),))

#     lookup = {}
#     for row in cr.dictfetchall():
#         mid = row['message_id']
#         lookup.setdefault(mid, []).append({
#             'id':       row['att_id'],
#             'name':     row['att_name'],
#             'mimetype': row['att_mimetype'] or 'application/octet-stream',
#             'url':      '/web/content/%s?download=true' % row['att_id'],
#         })
#     return lookup


# # ─────────────────────────────────────────────────────────────────────────────
# # Message serialiser
# # ─────────────────────────────────────────────────────────────────────────────

# def _serialise_message(msg, ticket, attachment_lookup=None):
#     """
#     Convert one mail.message record into a plain dict.

#     attachment_lookup — pre-built dict from _prefetch_message_attachments().
#     If None (defensive fallback), attachments will be an empty list.
#     Never call msg.attachment_ids here — it silently returns [] for public
#     users due to ir.attachment record rules in Odoo 19.
#     """
#     partner     = msg.author_id
#     author_type = _resolve_author_type(partner)

#     assigned_pid = (
#         ticket.user_id.partner_id.id
#         if ticket.user_id and ticket.user_id.partner_id
#         else False
#     )

#     if author_type in ('portal_user', 'public'):
#         direction = 'inbound'
#     elif assigned_pid and partner and partner.id == assigned_pid:
#         direction = 'outbound'
#     else:
#         direction = 'internal'

#     subtype     = msg.subtype_id
#     mt_note_ref = request.env.ref('mail.mt_note', raise_if_not_found=False)
#     is_internal_note = bool(
#         subtype and mt_note_ref and subtype.id == mt_note_ref.id
#     )

#     return {
#         'message_id':       msg.id,
#         'parent_id':        msg.parent_id.id if msg.parent_id else None,
#         'body_html':        msg.body or '',
#         'body_text':        _strip_html(msg.body),
#         'message_type':     msg.message_type or '',
#         'subtype_name':     subtype.name if subtype else None,
#         'is_internal_note': is_internal_note,
#         'direction':        direction,
#         'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
#         # ── Resolved via raw SQL prefetch — bypasses ir.attachment record   ──
#         # ── rules that silently drop attachments for auth='public' requests ──
#         'attachments':      (attachment_lookup or {}).get(msg.id, []),
#         'author': {
#             'id':                partner.id if partner else None,
#             'name':              partner.name if partner else 'Unknown',
#             'email':             partner.email if partner else None,
#             'user_type':         author_type,
#             'is_assigned_agent': bool(
#                 assigned_pid and partner and partner.id == assigned_pid
#             ),
#         },
#         'reply_count': 0,
#         'replies':     [],
#     }


# def _normalise_orphan_parent_ids(flat_messages):
#     message_ids = {msg['message_id'] for msg in flat_messages}
#     for msg in flat_messages:
#         if msg['parent_id'] and msg['parent_id'] not in message_ids:
#             msg['parent_id'] = None
#     return flat_messages


# # ─────────────────────────────────────────────────────────────────────────────
# # Tree / hybrid builders
# # ─────────────────────────────────────────────────────────────────────────────

# def _build_tree(flat_messages):
#     index = {m['message_id']: m for m in flat_messages}
#     roots = []
#     for msg in flat_messages:
#         pid = msg['parent_id']
#         if pid and pid in index:
#             parent = index[pid]
#             parent['replies'].append(msg)
#             parent['reply_count'] += 1
#         else:
#             roots.append(msg)

#     def _sort_level(nodes):
#         nodes.sort(key=lambda m: m['date'] or '')
#         for node in nodes:
#             if node['replies']:
#                 _sort_level(node['replies'])

#     _sort_level(roots)
#     return roots


# def _build_hybrid(flat_messages):
#     mid_set      = {m['message_id'] for m in flat_messages}
#     children_map = {}
#     roots        = []

#     for msg in flat_messages:
#         pid = msg['parent_id']
#         if pid and pid in mid_set:
#             children_map.setdefault(pid, []).append(msg)
#         else:
#             roots.append(msg)

#     roots.sort(key=lambda m: m['date'] or '')
#     for kids in children_map.values():
#         kids.sort(key=lambda m: m['date'] or '')

#     timeline = []

#     def _dfs(msg, depth, thread_root_id):
#         entry = {k: v for k, v in msg.items() if k != 'replies'}
#         entry['depth']          = depth
#         entry['thread_root_id'] = thread_root_id
#         timeline.append(entry)
#         for child in children_map.get(msg['message_id'], []):
#             _dfs(child, depth + 1, thread_root_id)

#     for root in roots:
#         _dfs(root, 0, root['message_id'])

#     return timeline


# # ─────────────────────────────────────────────────────────────────────────────
# # Controller
# # ─────────────────────────────────────────────────────────────────────────────

# class HelpdeskConversationController(http.Controller):

#     MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

#     # =========================================================================
#     # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
#     # =========================================================================

#     @http.route(
#         '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
#         type='http',
#         auth='public',
#         methods=['GET'],
#         csrf=False,
#         save_session=False,
#     )
#     def get_conversation(self, ticket_id, **query_params):
#         mode             = query_params.get('mode', 'tree').strip().lower()
#         include_internal = query_params.get('include_internal', '1') != '0'
#         include_system   = query_params.get('include_system',   '0') == '1'

#         if mode not in ('tree', 'flat', 'hybrid'):
#             return self._json_response(
#                 {"status": "error",
#                  "message": "Invalid mode '%s'. Accepted: tree, flat, hybrid." % mode},
#                 status=400,
#             )

#         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
#         if not ticket.exists():
#             return self._json_response(
#                 {"status": "error", "message": "Ticket #%s not found." % ticket_id},
#                 status=404,
#             )

#         allowed_types = ['comment', 'email']
#         if include_system:
#             allowed_types += ['notification', 'user_notification']

#         domain = [
#             ('model',        '=',  'helpdesk.ticket'),
#             ('res_id',       '=',  ticket_id),
#             ('message_type', 'in', allowed_types),
#         ]

#         if not include_internal:
#             mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
#             if mt_note:
#                 domain.append(('subtype_id', '!=', mt_note.id))

#         try:
#             messages = request.env['mail.message'].sudo().search(
#                 domain, order='date asc',
#             )
#         except Exception as exc:
#             _logger.error(
#                 "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
#                 ticket_id, exc,
#             )
#             return self._json_response(
#                 {"status": "error", "message": "Failed to retrieve conversation."},
#                 status=500,
#             )

#         # ── ONE query for ALL attachments across ALL messages ─────────────────
#         # msg.attachment_ids silently returns [] under auth='public' in Odoo 19
#         # because ir.attachment record rules fire against the public user even
#         # on a sudo() mail.message recordset. Raw SQL JOIN bypasses this.
#         attachment_lookup = _prefetch_message_attachments(
#             request.env.cr, messages.ids
#         )

#         flat_list = _normalise_orphan_parent_ids(
#             [_serialise_message(msg, ticket, attachment_lookup) for msg in messages]
#         )

#         if mode == 'tree':
#             conversation = _build_tree(flat_list)
#         elif mode == 'hybrid':
#             conversation = _build_hybrid(flat_list)
#         else:
#             conversation = flat_list

#         assigned_agent = None
#         if ticket.user_id:
#             assigned_agent = {
#                 'id':    ticket.user_id.id,
#                 'name':  ticket.user_id.name,
#                 'email': ticket.user_id.email,
#             }

#         return self._json_response({
#             'status':         'success',
#             'ticket_id':      ticket.id,
#             'ticket_name':    ticket.name or '',
#             'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
#             'assigned_agent': assigned_agent,
#             'total_messages': len(flat_list),
#             'mode':           mode,
#             'conversation':   conversation,
#         })

#     # =========================================================================
#     # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
#     # =========================================================================

#     @http.route(
#         '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
#         type='http',
#         auth='public',
#         methods=['POST'],
#         csrf=False,
#         save_session=False,
#     )
#     def inbound_message(self, ticket_id, **_kwargs):
#         # ── Parse request body ───────────────────────────────────────────────
#         try:
#             payload, uploaded_files = self._parse_inbound_payload()
#         except ValueError as exc:
#             return self._json_response(
#                 {"status": "error", "message": str(exc)}, status=400,
#             )

#         sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
#         sender_email    = str(payload.get('sender_email', '')).strip()
#         body            = str(payload.get('body',         '')).strip()
#         raw_parent      = payload.get('parent_message_id')
#         raw_attachments = payload.get('attachments') or []

#         if not body and not raw_attachments and not uploaded_files:
#             return self._json_response(
#                 {"status": "error",
#                  "message": "'body' or 'attachments' is required."},
#                 status=422,
#             )

#         # ── Fetch ticket ─────────────────────────────────────────────────────
#         ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
#         if not ticket.exists():
#             return self._json_response(
#                 {"status": "error",
#                  "message": "Ticket #%s not found." % ticket_id},
#                 status=404,
#             )

#         # ── Resolve author partner ───────────────────────────────────────────
#         author_id = False
#         if sender_email:
#             Partner = request.env['res.partner'].sudo()
#             partner = Partner.search([('email', '=', sender_email)], limit=1)
#             if not partner:
#                 partner = Partner.create({
#                     'name':  sender_name or sender_email,
#                     'email': sender_email,
#                 })
#             author_id = partner.id

#         # ── Resolve optional parent_message_id ──────────────────────────────
#         parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

#         # ── Validate & decode attachment data BEFORE any DB write ────────────
#         try:
#             attachment_tuples  = self._prepare_inbound_attachments(raw_attachments)
#             attachment_tuples += self._prepare_uploaded_attachments(uploaded_files)
#         except ValueError as exc:
#             return self._json_response(
#                 {"status": "error", "message": str(exc)}, status=422,
#             )
#         except Exception as exc:
#             _logger.error(
#                 "[Zencore] Unexpected error processing attachments "
#                 "for ticket_id=%s: %s", ticket_id, exc,
#             )
#             return self._json_response(
#                 {"status": "error", "message": "Failed to process attachments."},
#                 status=500,
#             )

#         # ── Step 1: Post message (body only, no attachments yet) ─────────────
#         chatter_body = Markup("<p>%s</p>" % escape(body or ""))

#         try:
#             message = ticket.message_post(
#                 body=chatter_body,
#                 author_id=author_id or False,
#                 message_type='comment',
#                 subtype_xmlid='mail.mt_note',
#                 parent_id=parent_id or False,
#             )
#         except Exception as exc:
#             _logger.error(
#                 "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
#                 ticket_id, exc,
#             )
#             return self._json_response(
#                 {"status": "error", "message": "Failed to post message."},
#                 status=500,
#             )

#         # ── Step 2 + 3: Create ir.attachment records, then link to message ───
#         attachment_ids = self._create_and_link_attachments(
#             ticket, message, attachment_tuples
#         )

#         # ── Notify assigned agent ────────────────────────────────────────────
#         ticket._notify_assigned_user_on_inbound()

#         return self._json_response({
#             "status":         "success",
#             "message_id":     message.id,
#             "ticket_id":      ticket.id,
#             "attachment_ids": attachment_ids,
#         })

#     # ─────────────────────────────────────────────────────────────────────────
#     # Attachment helpers
#     # ─────────────────────────────────────────────────────────────────────────

#     @staticmethod
#     def _prepare_inbound_attachments(raw_attachments):
#         """
#         Decode and validate base64 attachments from a JSON payload.
#         Returns a list of (filename, file_bytes, mimetype) tuples.
#         Raises ValueError on the first invalid entry.
#         """
#         if not isinstance(raw_attachments, list):
#             raise ValueError("'attachments' must be a list.")

#         result = []
#         for index, item in enumerate(raw_attachments, start=1):
#             if not isinstance(item, dict):
#                 raise ValueError("Attachment #%s must be an object." % index)

#             filename = HelpdeskConversationController._clean_filename(
#                 item.get('filename') or item.get('name') or 'attachment-%s' % index
#             )
#             raw_data = item.get('data') or item.get('datas') or item.get('content')
#             if not raw_data:
#                 raise ValueError(
#                     "Attachment '%s' is missing base64 data." % filename
#                 )

#             raw_data = str(raw_data).strip()
#             # Strip data-URI prefix: "data:image/png;base64,<data>"
#             if ',' in raw_data and raw_data.lower().startswith('data:'):
#                 raw_data = raw_data.split(',', 1)[1]

#             try:
#                 file_content = base64.b64decode(raw_data, validate=True)
#             except (binascii.Error, ValueError):
#                 raise ValueError(
#                     "Attachment '%s' has invalid base64 data." % filename
#                 )

#             HelpdeskConversationController._check_attachment_size(
#                 filename, file_content
#             )

#             mimetype = (
#                 item.get('mimetype')
#                 or mimetypes.guess_type(filename)[0]
#                 or 'application/octet-stream'
#             )
#             result.append((filename, file_content, mimetype))
#         return result

#     @staticmethod
#     def _prepare_uploaded_attachments(uploaded_files):
#         """
#         Read and validate files from a multipart/form-data upload.

#         FIX: stream.seek(0) resets Werkzeug stream position before reading
#         so file_content is never silently empty.

#         Returns a list of (filename, file_bytes, mimetype) tuples.
#         Skips files with no name or zero-byte content (with a warning).
#         """
#         result = []
#         for uploaded_file in uploaded_files:
#             if not uploaded_file or not uploaded_file.filename:
#                 continue

#             filename = HelpdeskConversationController._clean_filename(
#                 uploaded_file.filename
#             )

#             try:
#                 uploaded_file.stream.seek(0)
#             except Exception:
#                 pass  # some stream types don't support seek; best-effort
#             file_content = uploaded_file.stream.read()

#             if not file_content:
#                 _logger.warning(
#                     "[Zencore] Skipping multipart file '%s': stream yielded "
#                     "0 bytes (stream may have already been consumed).",
#                     filename,
#                 )
#                 continue

#             HelpdeskConversationController._check_attachment_size(
#                 filename, file_content
#             )

#             mimetype = (
#                 getattr(uploaded_file, 'mimetype', None)
#                 or getattr(uploaded_file, 'content_type', None)
#                 or mimetypes.guess_type(filename)[0]
#                 or 'application/octet-stream'
#             )
#             result.append((filename, file_content, mimetype))
#         return result

#     @staticmethod
#     def _create_and_link_attachments(ticket, message, attachment_tuples):
#         """
#         Create ir.attachment records and link them to both the ticket and
#         the chatter message.

#         Two things happen here:
#           A) ir.attachment created with res_model='helpdesk.ticket', res_id=ticket.id
#              → file appears in the ticket's Attachments tab.
#           B) M2M link written directly on the mail.message record:
#                message.write({'attachment_ids': [(4, att_id), ...]})
#              → file appears inside the chatter message bubble.

#         datas must be a str (not bytes): base64.b64encode() returns bytes;
#         .decode() converts to ASCII string which is what Odoo 19 expects
#         for all Binary/datas fields.

#         Returns a list of ir.attachment IDs (empty list when no files).
#         """
#         if not attachment_tuples:
#             return []

#         att_ids = []
#         for filename, file_content, mimetype in attachment_tuples:
#             att = request.env['ir.attachment'].sudo().create({
#                 'name':      filename,
#                 'type':      'binary',
#                 'datas':     base64.b64encode(file_content).decode(),
#                 'mimetype':  mimetype,
#                 'res_model': 'helpdesk.ticket',
#                 'res_id':    ticket.id,
#             })
#             att_ids.append(att.id)
#             _logger.debug(
#                 "[Zencore] Created attachment id=%s name='%s' ticket_id=%s",
#                 att.id, filename, ticket.id,
#             )

#         if att_ids:
#             # (4, id) = "add link" ORM command for Many2many.
#             message.sudo().write({
#                 'attachment_ids': [(4, att_id) for att_id in att_ids],
#             })
#             _logger.debug(
#                 "[Zencore] Linked %s attachment(s) to message_id=%s",
#                 len(att_ids), message.id,
#             )

#         return att_ids

#     # ─────────────────────────────────────────────────────────────────────────
#     # Shared private helpers
#     # ─────────────────────────────────────────────────────────────────────────

#     def _parse_inbound_payload(self):
#         """
#         Support JSON base64 attachments and multipart/form-data file uploads.

#         Collects ALL uploaded files regardless of field name using
#         files.to_dict(flat=False) so no field name is silently missed.
#         """
#         content_type = (request.httprequest.content_type or '').lower()
#         if content_type.startswith('multipart/form-data'):
#             payload = dict(request.httprequest.form.items())

#             attachments = payload.get('attachments')
#             if attachments:
#                 try:
#                     payload['attachments'] = json.loads(attachments)
#                 except (TypeError, ValueError):
#                     raise ValueError(
#                         "'attachments' must be valid JSON when sent as form-data."
#                     )

#             # Capture every uploaded file regardless of field name
#             uploaded_files = []
#             for file_list in request.httprequest.files.to_dict(flat=False).values():
#                 uploaded_files.extend(file_list)

#             _logger.debug(
#                 "[Zencore] multipart upload: %d file(s) received across %d field(s)",
#                 len(uploaded_files),
#                 len(request.httprequest.files.to_dict(flat=False)),
#             )
#             return payload, uploaded_files

#         raw = request.httprequest.data
#         if not raw:
#             raise ValueError('Empty request body.')
#         try:
#             return json.loads(raw), []
#         except (ValueError, TypeError) as exc:
#             _logger.warning(
#                 "[Zencore] Malformed JSON in inbound_message: %s", exc
#             )
#             raise ValueError('Invalid JSON payload.')

#     @staticmethod
#     def _check_attachment_size(filename, file_content):
#         if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
#             raise ValueError(
#                 "Attachment '%s' exceeds 10MB limit." % filename
#             )

#     @staticmethod
#     def _clean_filename(filename):
#         filename = secure_filename(str(filename or '').strip())
#         return filename or 'attachment'

#     @staticmethod
#     def _json_response(data, status=200):
#         return Response(
#             json.dumps(data, default=str),
#             content_type='application/json; charset=utf-8',
#             status=status,
#         )

#     @staticmethod
#     def _resolve_parent_message_id(raw_parent, ticket_id):
#         """Validate and resolve parent_message_id. Returns int id or False."""
#         if raw_parent is None:
#             return False

#         try:
#             parent_int = int(raw_parent)
#         except (ValueError, TypeError):
#             _logger.warning(
#                 "[Zencore] parent_message_id='%s' is not an integer "
#                 "(ticket_id=%s). Ignoring.",
#                 raw_parent, ticket_id,
#             )
#             return False

#         parent_msg = request.env['mail.message'].sudo().browse(parent_int)
#         if not parent_msg.exists():
#             _logger.warning(
#                 "[Zencore] parent_message_id=%s does not exist "
#                 "(ticket_id=%s). Ignoring.",
#                 parent_int, ticket_id,
#             )
#             return False

#         if (
#             parent_msg.model != 'helpdesk.ticket'
#             or parent_msg.res_id != ticket_id
#         ):
#             _logger.warning(
#                 "[Zencore] parent_message_id=%s does not belong to "
#                 "ticket_id=%s. Ignoring.",
#                 parent_int, ticket_id,
#             )
#             return False

#         return parent_msg.id
"""
zencore_helpdesk_conversion_api — controllers/main.py

Endpoints
─────────
  POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
  GET  /api/v1/helpdesk/ticket/<ticket_id>/conversation

Auth: public on all routes.

Attachment design (Odoo 19 — WRITE)
─────────────────────────────────────
message_post(attachment_ids=[...]) passes IDs through
_message_post_process_attachments which silently drops any attachment
whose res_model is already set to something other than
'mail.compose.message'.

Correct pattern:
  1. Post the message (body only, no attachments).
  2. Create ir.attachment with res_model='helpdesk.ticket', res_id=ticket.id
     so the files appear in the ticket's Attachments tab.
  3. Generate an access token immediately on the new attachment so the
     returned URL is publicly accessible without a session cookie.
  4. Write the M2M link directly:
       message.write({'attachment_ids': [(4, att_id), ...]})

Attachment design (Odoo 19 — READ / GET conversation)
───────────────────────────────────────────────────────
TWO separate problems cause attachments to be missing or return 404:

  PROBLEM 1 — ORM silently returns []:
    msg.attachment_ids under auth='public' fires ir.attachment record
    rules against the public user and returns an empty set even when the
    mail.message was fetched via sudo().
    FIX: raw SQL JOIN over message_attachment_rel → ir_attachment.

  PROBLEM 2 — /web/content/<id>?download=true returns 404:
    That route requires an authenticated session. Public callers get 404.
    FIX: generate_access_token() on each attachment. The URL becomes
    /web/content/<id>?access_token=<token>&download=true which is
    session-free and works in Postman / external portals.
"""

import base64
import binascii
import hmac
import json
import logging
import mimetypes
from email.utils import formataddr
from html.parser import HTMLParser
from urllib.parse import urlencode

from markupsafe import Markup, escape
from werkzeug.utils import secure_filename

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HTML → plain-text stripper
# ─────────────────────────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return ' '.join(self._parts).strip()


def _strip_html(html):
    if not html:
        return ''
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return html


# ─────────────────────────────────────────────────────────────────────────────
# Author-type resolver
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_author_type(partner):
    if not partner:
        return 'public'
    users = partner.user_ids
    if not users:
        return 'public'
    for user in users:
        if not user.share:
            return 'internal_user'
    return 'portal_user'


def _attachment_download_url(attachment_id, access_token, env):
    """Build a token-protected, browser-safe attachment download URL."""
    query = urlencode({
        'access_token': access_token,
        'download': 'true',
        'db': env.cr.dbname,
    })
    return (
        '/api/v1/helpdesk/conversation/attachments/%s/download?%s'
        % (attachment_id, query)
    )


def _get_ticket_help_topic(ticket):
    """Return help_topic when the custom field is installed."""
    if 'help_topic' not in ticket._fields:
        return ''
    return ticket.help_topic or ''


# ─────────────────────────────────────────────────────────────────────────────
# Attachment prefetch — ONE SQL query for ALL messages
#
# PROBLEM 1 FIX — raw SQL bypasses ir.attachment record rules:
#   msg.attachment_ids under auth='public' silently returns [] because
#   ir.attachment record rules fire against the public user even when the
#   parent mail.message was fetched via sudo(). Raw SQL JOIN avoids this.
#
# PROBLEM 2 FIX — access token URLs work without a session cookie:
#   /web/content/<id>?download=true requires an authenticated session →
#   external callers (Postman, portal) get a 404.
#   generate_access_token() produces an unguessable token so the URL
#   becomes /web/content/<id>?access_token=<token>&download=true which
#   Odoo serves to any caller regardless of session state.
# ─────────────────────────────────────────────────────────────────────────────

def _prefetch_message_attachments(cr, env, message_ids):
    """
    Fetch all attachment metadata for a set of message IDs in ONE SQL query,
    then ensure every attachment has an access token so the returned URLs
    are accessible without a session cookie.

    Parameters
    ──────────
    cr          — database cursor (request.env.cr)
    env         — ORM environment (request.env) — needed for token generation
    message_ids — list/tuple of mail.message IDs

    Returns
    ───────
    { message_id: [ {id, name, mimetype, url}, ... ] }
    Empty dict when message_ids is empty (safe to call unconditionally).
    """
    if not message_ids:
        return {}

    # ── Step 1: fetch attachment rows + existing tokens in one query ──────────
    cr.execute("""
        SELECT
            mar.message_id,
            ia.id           AS att_id,
            ia.name         AS att_name,
            ia.mimetype     AS att_mimetype,
            ia.access_token AS att_token
        FROM   message_attachment_rel  mar
        JOIN   ir_attachment           ia  ON ia.id = mar.attachment_id
        WHERE  mar.message_id = ANY(%s)
        ORDER  BY mar.message_id, ia.id
    """, (list(message_ids),))

    rows = cr.dictfetchall()

    if not rows:
        return {}

    # ── Step 2: generate access tokens for attachments that don't have one ────
    #
    # generate_access_token() writes the token to ir_attachment and returns
    # a list aligned with the recordset order.
    #
    # We call it in a single batch (one ORM call for all missing tokens)
    # rather than one call per attachment.
    no_token_ids = list(dict.fromkeys(
        row['att_id'] for row in rows
        if not row['att_token']
    ))

    generated_token_map = {}
    if no_token_ids:
        attachments = env['ir.attachment'].sudo().browse(no_token_ids).exists()
        try:
            tokens = attachments.generate_access_token()
            # tokens is a list aligned with attachments recordset order
            generated_token_map = dict(zip(attachments.ids, tokens))
            _logger.debug(
                "[Zencore] Generated access tokens for %d attachment(s).",
                len(no_token_ids),
            )
        except Exception as exc:
            _logger.error(
                "[Zencore] Failed to generate access tokens for attachments %s: %s",
                no_token_ids, exc,
            )

    # ── Step 3: build lookup dict with access-token URLs ─────────────────────
    lookup = {}
    for row in rows:
        mid    = row['message_id']
        att_id = row['att_id']

        # Use existing token first, then a newly generated one.  Do not expose
        # a session-only /web/content link: API callers cannot use it reliably.
        token = row['att_token'] or generated_token_map.get(att_id)

        if token:
            url = _attachment_download_url(att_id, token, env)
        else:
            _logger.warning(
                "[Zencore] Attachment id=%s has no access token; omitting "
                "the unusable download URL.",
                att_id,
            )
            url = None

        lookup.setdefault(mid, []).append({
            'id':       att_id,
            'name':     row['att_name'],
            'mimetype': (
                mimetypes.guess_type(row['att_name'] or '')[0]
                or row['att_mimetype']
                or 'application/octet-stream'
            ),
            'url':      url,
        })

    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# Message serialiser
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_message(msg, ticket, attachment_lookup=None):
    """
    Convert one mail.message record into a plain dict.

    attachment_lookup — pre-built dict from _prefetch_message_attachments().
    Never call msg.attachment_ids here — it silently returns [] for public
    users due to ir.attachment record rules in Odoo 19.
    """
    partner     = msg.author_id
    author_type = _resolve_author_type(partner)

    assigned_pid = (
        ticket.user_id.partner_id.id
        if ticket.user_id and ticket.user_id.partner_id
        else False
    )

    if author_type in ('portal_user', 'public'):
        direction = 'inbound'
    elif assigned_pid and partner and partner.id == assigned_pid:
        direction = 'outbound'
    else:
        direction = 'internal'

    subtype     = msg.subtype_id
    mt_note_ref = request.env.ref('mail.mt_note', raise_if_not_found=False)
    is_internal_note = bool(
        subtype and mt_note_ref and subtype.id == mt_note_ref.id
    )

    return {
        'message_id':       msg.id,
        'parent_id':        msg.parent_id.id if msg.parent_id else None,
        'body_html':        msg.body or '',
        'body_text':        _strip_html(msg.body),
        'message_type':     msg.message_type or '',
        'subtype_name':     subtype.name if subtype else None,
        'is_internal_note': is_internal_note,
        'direction':        direction,
        'date':             msg.date.strftime('%Y-%m-%dT%H:%M:%SZ') if msg.date else None,
        # ── Raw SQL prefetch with access-token URLs.                         ──
        # ── msg.attachment_ids returns [] for public users (Odoo 19).        ──
        # ── /web/content/<id>?download=true returns 404 without a session.   ──
        'attachments':      (attachment_lookup or {}).get(msg.id, []),
        'author': {
            'id':                partner.id if partner else None,
            'name':              partner.name if partner else 'Unknown',
            'email':             partner.email if partner else None,
            'user_type':         author_type,
            'is_assigned_agent': bool(
                assigned_pid and partner and partner.id == assigned_pid
            ),
        },
        'reply_count': 0,
        'replies':     [],
    }


def _normalise_orphan_parent_ids(flat_messages):
    message_ids = {msg['message_id'] for msg in flat_messages}
    for msg in flat_messages:
        if msg['parent_id'] and msg['parent_id'] not in message_ids:
            msg['parent_id'] = None
    return flat_messages


# ─────────────────────────────────────────────────────────────────────────────
# Tree / hybrid builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_tree(flat_messages):
    index = {m['message_id']: m for m in flat_messages}
    roots = []
    for msg in flat_messages:
        pid = msg['parent_id']
        if pid and pid in index:
            parent = index[pid]
            parent['replies'].append(msg)
            parent['reply_count'] += 1
        else:
            roots.append(msg)

    def _sort_level(nodes):
        nodes.sort(key=lambda m: m['date'] or '')
        for node in nodes:
            if node['replies']:
                _sort_level(node['replies'])

    _sort_level(roots)
    return roots


def _build_hybrid(flat_messages):
    mid_set      = {m['message_id'] for m in flat_messages}
    children_map = {}
    roots        = []

    for msg in flat_messages:
        pid = msg['parent_id']
        if pid and pid in mid_set:
            children_map.setdefault(pid, []).append(msg)
        else:
            roots.append(msg)

    roots.sort(key=lambda m: m['date'] or '')
    for kids in children_map.values():
        kids.sort(key=lambda m: m['date'] or '')

    timeline = []

    def _dfs(msg, depth, thread_root_id):
        entry = {k: v for k, v in msg.items() if k != 'replies'}
        entry['depth']          = depth
        entry['thread_root_id'] = thread_root_id
        timeline.append(entry)
        for child in children_map.get(msg['message_id'], []):
            _dfs(child, depth + 1, thread_root_id)

    for root in roots:
        _dfs(root, 0, root['message_id'])

    return timeline


# ─────────────────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────────────────

class HelpdeskConversationController(http.Controller):

    MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

    # =========================================================================
    # GET /api/v1/helpdesk/ticket/<ticket_id>/conversation
    # =========================================================================

    @http.route(
        '/api/v1/helpdesk/ticket/<int:ticket_id>/conversation',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def get_conversation(self, ticket_id, **query_params):
        mode             = query_params.get('mode', 'tree').strip().lower()
        include_internal = query_params.get('include_internal', '1') != '0'
        include_system   = query_params.get('include_system',   '0') == '1'

        if mode not in ('tree', 'flat', 'hybrid'):
            return self._json_response(
                {"status": "error",
                 "message": "Invalid mode '%s'. Accepted: tree, flat, hybrid." % mode},
                status=400,
            )

        ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return self._json_response(
                {"status": "error", "message": "Ticket #%s not found." % ticket_id},
                status=404,
            )

        allowed_types = ['comment', 'email']
        if include_system:
            allowed_types += ['notification', 'user_notification']

        domain = [
            ('model',        '=',  'helpdesk.ticket'),
            ('res_id',       '=',  ticket_id),
            ('message_type', 'in', allowed_types),
        ]

        if not include_internal:
            mt_note = request.env.ref('mail.mt_note', raise_if_not_found=False)
            if mt_note:
                domain.append(('subtype_id', '!=', mt_note.id))

        try:
            messages = request.env['mail.message'].sudo().search(
                domain, order='date asc',
            )
        except Exception as exc:
            _logger.error(
                "[Zencore] Failed to fetch messages for ticket_id=%s: %s",
                ticket_id, exc,
            )
            return self._json_response(
                {"status": "error", "message": "Failed to retrieve conversation."},
                status=500,
            )

        # ── Fetch attachments: ONE SQL query + access token generation ────────
        #
        # PROBLEM 1: msg.attachment_ids returns [] for auth='public' requests
        #            (ir.attachment record rules — bypassed by raw SQL JOIN).
        # PROBLEM 2: /web/content/<id>?download=true → 404 without a session
        #            (fixed by access_token URLs generated here).
        attachment_lookup = _prefetch_message_attachments(
            request.env.cr,
            request.env,
            messages.ids,
        )

        flat_list = _normalise_orphan_parent_ids(
            [_serialise_message(msg, ticket, attachment_lookup) for msg in messages]
        )

        if mode == 'tree':
            conversation = _build_tree(flat_list)
        elif mode == 'hybrid':
            conversation = _build_hybrid(flat_list)
        else:
            conversation = flat_list

        assigned_agent = None
        if ticket.user_id:
            assigned_agent = {
                'id':    ticket.user_id.id,
                'name':  ticket.user_id.name,
                'email': ticket.user_id.email,
            }

        return self._json_response({
            'status':         'success',
            'ticket_id':      ticket.id,
            'ticket_name':    ticket.name or '',
            'help_topic':     _get_ticket_help_topic(ticket),
            'ticket_status':  ticket.stage_id.name if ticket.stage_id else None,
            'assigned_agent': assigned_agent,
            'total_messages': len(flat_list),
            'mode':           mode,
            'conversation':   conversation,
        })

    # =========================================================================
    # GET /api/v1/helpdesk/conversation/attachments/<attachment_id>/download
    # =========================================================================

    @http.route(
        '/api/v1/helpdesk/conversation/attachments/<int:attachment_id>/download',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def download_attachment(self, attachment_id, **params):
        """
        Stream a chatter attachment as a real file download.

        The access token is generated when the conversation is serialised.
        Serving the file here avoids a session-dependent /web/content request
        and preserves the original bytes, filename, and Office MIME type.
        """
        access_token = (params.get('access_token') or '').strip()
        if not access_token:
            return self._json_response(
                {'status': 'error', 'message': 'Attachment access_token is required.'},
                status=403,
            )

        try:
            attachment = (
                request.env['ir.attachment']
                .sudo()
                .browse(attachment_id)
                .exists()
            )
            if not attachment:
                return self._json_response(
                    {'status': 'error', 'message': 'Attachment not found.'},
                    status=404,
                )

            stored_token = attachment.access_token
            if not stored_token:
                generated_tokens = attachment.generate_access_token()
                stored_token = (
                    generated_tokens[0]
                    if generated_tokens
                    else attachment.access_token
                )

            if not stored_token or not hmac.compare_digest(
                str(stored_token), str(access_token),
            ):
                return self._json_response(
                    {'status': 'error', 'message': 'Invalid attachment access_token.'},
                    status=403,
                )

            # DOCX files are ZIP containers. Prefer the filename extension so
            # a generic stored type (such as application/zip) cannot make a
            # browser or client treat the Word document as plain binary data.
            download_mimetype = (
                mimetypes.guess_type(attachment.name or '')[0]
                or attachment.mimetype
                or 'application/octet-stream'
            )
            stream = request.env['ir.binary']._get_stream_from(
                attachment,
                field_name='raw',
                filename=attachment.name,
                mimetype=download_mimetype,
            )
            return stream.get_response(as_attachment=True)

        except Exception as exc:
            _logger.exception(
                '[Zencore] Failed downloading attachment id=%s: %s',
                attachment_id,
                exc,
            )
            return self._json_response(
                {'status': 'error', 'message': 'Failed to download attachment.'},
                status=500,
            )

    # =========================================================================
    # POST /api/v1/helpdesk/ticket/<ticket_id>/inbound_message
    # =========================================================================

    @http.route(
        '/api/v1/helpdesk/ticket/<int:ticket_id>/inbound_message',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def inbound_message(self, ticket_id, **_kwargs):
        # ── Parse request body ───────────────────────────────────────────────
        try:
            payload, uploaded_files = self._parse_inbound_payload()
        except ValueError as exc:
            return self._json_response(
                {"status": "error", "message": str(exc)}, status=400,
            )

        sender_name     = str(payload.get('sender_name',  'Unknown Sender')).strip()
        sender_email    = str(payload.get('sender_email', '')).strip()
        body            = str(payload.get('body',         '')).strip()
        raw_parent      = payload.get('parent_message_id')
        raw_attachments = payload.get('attachments') or []

        if not body and not raw_attachments and not uploaded_files:
            return self._json_response(
                {"status": "error",
                 "message": "'body' or 'attachments' is required."},
                status=422,
            )

        # ── Fetch ticket ─────────────────────────────────────────────────────
        ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return self._json_response(
                {"status": "error",
                 "message": "Ticket #%s not found." % ticket_id},
                status=404,
            )

        # ── Resolve author partner ───────────────────────────────────────────
        author_id = False
        if sender_email:
            Partner = request.env['res.partner'].sudo()
            partner = Partner.search([('email', '=', sender_email)], limit=1)
            if not partner:
                partner = Partner.create({
                    'name':  sender_name or sender_email,
                    'email': sender_email,
                })
            author_id = partner.id

        # ── Resolve optional parent_message_id ──────────────────────────────
        parent_id = self._resolve_parent_message_id(raw_parent, ticket_id)

        # ── Validate & decode attachment data BEFORE any DB write ────────────
        try:
            attachment_tuples  = self._prepare_inbound_attachments(raw_attachments)
            attachment_tuples += self._prepare_uploaded_attachments(uploaded_files)
        except ValueError as exc:
            return self._json_response(
                {"status": "error", "message": str(exc)}, status=422,
            )
        except Exception as exc:
            _logger.error(
                "[Zencore] Unexpected error processing attachments "
                "for ticket_id=%s: %s", ticket_id, exc,
            )
            return self._json_response(
                {"status": "error", "message": "Failed to process attachments."},
                status=500,
            )

        # ── Step 1: Post message (body only, no attachments yet) ─────────────
        chatter_body = Markup("<p>%s</p>" % escape(body or ""))
        email_from = (
            formataddr((sender_name or sender_email, sender_email))
            if sender_email
            else sender_name
        )

        try:
            message = ticket.message_post(
                body=chatter_body,
                author_id=author_id or False,
                email_from=email_from or None,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                parent_id=parent_id or False,
            )
        except Exception as exc:
            _logger.error(
                "[Zencore] Failed to post chatter message for ticket_id=%s: %s",
                ticket_id, exc,
            )
            return self._json_response(
                {"status": "error", "message": "Failed to post message."},
                status=500,
            )

        # ── Step 2 + 3: Create ir.attachment records, then link to message ───
        attachment_ids = self._create_and_link_attachments(
            ticket, message, attachment_tuples
        )

        # ── Notify assigned agent ────────────────────────────────────────────
        ticket._notify_assigned_user_on_inbound()

        return self._json_response({
            "status":         "success",
            "message_id":     message.id,
            "ticket_id":      ticket.id,
            "attachment_ids": attachment_ids,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Attachment helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _prepare_inbound_attachments(raw_attachments):
        """
        Decode and validate base64 attachments from a JSON payload.
        Returns a list of (filename, file_bytes, mimetype) tuples.
        Raises ValueError on the first invalid entry.
        """
        if not isinstance(raw_attachments, list):
            raise ValueError("'attachments' must be a list.")

        result = []
        for index, item in enumerate(raw_attachments, start=1):
            if not isinstance(item, dict):
                raise ValueError("Attachment #%s must be an object." % index)

            filename = HelpdeskConversationController._clean_filename(
                item.get('filename') or item.get('name') or 'attachment-%s' % index
            )
            raw_data = item.get('data') or item.get('datas') or item.get('content')
            if not raw_data:
                raise ValueError(
                    "Attachment '%s' is missing base64 data." % filename
                )

            raw_data = str(raw_data).strip()
            # Strip data-URI prefix: "data:image/png;base64,<data>"
            if ',' in raw_data and raw_data.lower().startswith('data:'):
                raw_data = raw_data.split(',', 1)[1]

            try:
                file_content = base64.b64decode(raw_data, validate=True)
            except (binascii.Error, ValueError):
                raise ValueError(
                    "Attachment '%s' has invalid base64 data." % filename
                )

            HelpdeskConversationController._check_attachment_size(
                filename, file_content
            )

            mimetype = (
                item.get('mimetype')
                or mimetypes.guess_type(filename)[0]
                or 'application/octet-stream'
            )
            result.append((filename, file_content, mimetype))
        return result

    @staticmethod
    def _prepare_uploaded_attachments(uploaded_files):
        """
        Read and validate files from a multipart/form-data upload.

        stream.seek(0) resets Werkzeug stream position before reading
        so file_content is never silently empty.

        Returns a list of (filename, file_bytes, mimetype) tuples.
        Skips files with no name or zero-byte content (with a warning).
        """
        result = []
        for uploaded_file in uploaded_files:
            if not uploaded_file or not uploaded_file.filename:
                continue

            filename = HelpdeskConversationController._clean_filename(
                uploaded_file.filename
            )

            try:
                uploaded_file.stream.seek(0)
            except Exception:
                pass
            file_content = uploaded_file.stream.read()

            if not file_content:
                _logger.warning(
                    "[Zencore] Skipping multipart file '%s': stream yielded "
                    "0 bytes (stream may have already been consumed).",
                    filename,
                )
                continue

            HelpdeskConversationController._check_attachment_size(
                filename, file_content
            )

            mimetype = (
                getattr(uploaded_file, 'mimetype', None)
                or getattr(uploaded_file, 'content_type', None)
                or mimetypes.guess_type(filename)[0]
                or 'application/octet-stream'
            )
            result.append((filename, file_content, mimetype))
        return result

    @staticmethod
    def _create_and_link_attachments(ticket, message, attachment_tuples):
        """
        Create ir.attachment records, generate access tokens immediately,
        and link them to both the ticket and the chatter message.

        Three things happen here:
          A) ir.attachment created with res_model='helpdesk.ticket', res_id=ticket.id
             → file appears in the ticket's Attachments tab.
          B) generate_access_token() called immediately so the attachment URL
             returned by GET /conversation works without a session cookie.
          C) M2M link written directly on the mail.message record:
               message.write({'attachment_ids': [(4, att_id), ...]})
             → file appears inside the chatter message bubble.

        datas must be a str (not bytes): .decode() converts base64 bytes
        to an ASCII string which is what Odoo 19 expects for Binary fields.

        Returns a list of ir.attachment IDs (empty list when no files).
        """
        if not attachment_tuples:
            return []

        att_ids = []
        for filename, file_content, mimetype in attachment_tuples:
            att = request.env['ir.attachment'].sudo().create({
                'name':      filename,
                'type':      'binary',
                'datas':     base64.b64encode(file_content).decode(),
                'mimetype':  mimetype,
                'res_model': 'helpdesk.ticket',
                'res_id':    ticket.id,
            })
            # Generate access token immediately so GET /conversation returns
            # a working URL without requiring a session cookie.
            try:
                att.generate_access_token()
            except Exception as exc:
                _logger.warning(
                    "[Zencore] Could not generate access token for "
                    "attachment id=%s name='%s': %s",
                    att.id, filename, exc,
                )
            att_ids.append(att.id)
            _logger.debug(
                "[Zencore] Created attachment id=%s name='%s' ticket_id=%s",
                att.id, filename, ticket.id,
            )

        if att_ids:
            # (4, id) = "add link" ORM command for Many2many.
            message.sudo().write({
                'attachment_ids': [(4, att_id) for att_id in att_ids],
            })
            _logger.debug(
                "[Zencore] Linked %s attachment(s) to message_id=%s",
                len(att_ids), message.id,
            )

        return att_ids

    # ─────────────────────────────────────────────────────────────────────────
    # Shared private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_inbound_payload(self):
        """
        Support JSON base64 attachments and multipart/form-data file uploads.

        Collects ALL uploaded files regardless of field name using
        files.to_dict(flat=False) so no field name is silently missed.
        """
        content_type = (request.httprequest.content_type or '').lower()
        if content_type.startswith('multipart/form-data'):
            payload = dict(request.httprequest.form.items())

            attachments = payload.get('attachments')
            if attachments:
                try:
                    payload['attachments'] = json.loads(attachments)
                except (TypeError, ValueError):
                    raise ValueError(
                        "'attachments' must be valid JSON when sent as form-data."
                    )

            # Capture every uploaded file regardless of field name
            uploaded_files = []
            for file_list in request.httprequest.files.to_dict(flat=False).values():
                uploaded_files.extend(file_list)

            _logger.debug(
                "[Zencore] multipart upload: %d file(s) received across %d field(s)",
                len(uploaded_files),
                len(request.httprequest.files.to_dict(flat=False)),
            )
            return payload, uploaded_files

        raw = request.httprequest.data
        if not raw:
            raise ValueError('Empty request body.')
        try:
            return json.loads(raw), []
        except (ValueError, TypeError) as exc:
            _logger.warning(
                "[Zencore] Malformed JSON in inbound_message: %s", exc
            )
            raise ValueError('Invalid JSON payload.')

    @staticmethod
    def _check_attachment_size(filename, file_content):
        if len(file_content) > HelpdeskConversationController.MAX_ATTACHMENT_BYTES:
            raise ValueError(
                "Attachment '%s' exceeds 10MB limit." % filename
            )

    @staticmethod
    def _clean_filename(filename):
        filename = secure_filename(str(filename or '').strip())
        return filename or 'attachment'

    @staticmethod
    def _json_response(data, status=200):
        return Response(
            json.dumps(data, default=str),
            content_type='application/json; charset=utf-8',
            status=status,
        )

    @staticmethod
    def _resolve_parent_message_id(raw_parent, ticket_id):
        """Validate and resolve parent_message_id. Returns int id or False."""
        if raw_parent is None:
            return False

        try:
            parent_int = int(raw_parent)
        except (ValueError, TypeError):
            _logger.warning(
                "[Zencore] parent_message_id='%s' is not an integer "
                "(ticket_id=%s). Ignoring.",
                raw_parent, ticket_id,
            )
            return False

        parent_msg = request.env['mail.message'].sudo().browse(parent_int)
        if not parent_msg.exists():
            _logger.warning(
                "[Zencore] parent_message_id=%s does not exist "
                "(ticket_id=%s). Ignoring.",
                parent_int, ticket_id,
            )
            return False

        if (
            parent_msg.model != 'helpdesk.ticket'
            or parent_msg.res_id != ticket_id
        ):
            _logger.warning(
                "[Zencore] parent_message_id=%s does not belong to "
                "ticket_id=%s. Ignoring.",
                parent_int, ticket_id,
            )
            return False

        return parent_msg.id
