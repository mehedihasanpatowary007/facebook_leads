# """
# zencore_helpdesk_conversion_api — helpdesk_ticket.py

# Sections covered:
#     1 — Suppress all outbound email from the chatter thread.
#     3 — Forward assigned-user replies to an external API.
#     4 — Always include parent_message_id in every outbound payload.
#     5 — Send a lightweight (no-thread) notification to the portal user
#         whenever the assigned user posts a reply.
# """

# import logging

# import requests

# from odoo import models

# _logger = logging.getLogger(__name__)


# class HelpdeskTicket(models.Model):
#     _inherit = 'helpdesk.ticket'

#     # ──────────────────────────────────────────────────────────────────────────
#     # SECTION 1 — Suppress Odoo's outbound email for all chatter messages.
#     #
#     # How Odoo normally works:
#     #   message_post()  →  _notify_thread()  →  _notify_thread_by_email()
#     #                                         →  _notify_thread_by_inbox()
#     #                                         →  push notifications, etc.
#     #
#     # By returning an empty dict here we stop the entire notification pipeline
#     # before any mail.mail record is created for followers.  The message itself
#     # is still persisted to mail.message — the chatter continues to work as an
#     # internal audit log.
#     # ──────────────────────────────────────────────────────────────────────────

#     def _notify_thread(self, message, msg_vals=False, **kwargs):
#         """
#         Override: suppress ALL outbound email / push / inbox notifications
#         that Odoo would normally dispatch to thread followers.

#         Chatter remains a read-only internal log.
#         """
#         return {}

#     # ──────────────────────────────────────────────────────────────────────────
#     # SECTION 3 + 4 + 5 — Intercept message_post.
#     #
#     # message_post() is the single entry-point for every chatter message in
#     # Odoo.  We call super() first so the message is saved to the DB, then
#     # inspect the author to decide whether to forward externally.
#     #
#     # Author detection logic:
#     #   - External inbound (controller) → sudo() env → author = OdooBot (uid=1)
#     #     → NOT the assigned user → NO forward triggered.
#     #   - Assigned agent posting via the Odoo UI → author = agent's partner_id
#     #     → matches ticket.user_id.partner_id → forward IS triggered.
#     # ──────────────────────────────────────────────────────────────────────────

#     def message_post(self, **kwargs):
#         """
#         Override: after persisting the chatter message, check if the author is
#         the ticket's assigned user.  If so:
#           - Forward the full payload to the external API  (Sections 3 + 4).
#           - Email a lightweight notification to the portal user  (Section 5).
#         """
#         message = super().message_post(**kwargs)

#         assigned_partner_id = (
#             self.user_id.partner_id.id
#             if self.user_id and self.user_id.partner_id
#             else False
#         )

#         if assigned_partner_id and message.author_id.id == assigned_partner_id:
#             self._forward_to_external_api(message)     # Sections 3 + 4
#             self._notify_portal_user_on_reply()        # Section 5

#         return message

#     # ──────────────────────────────────────────────────────────────────────────
#     # SECTION 3 + 4 — Forward payload to external system.
#     # ──────────────────────────────────────────────────────────────────────────

#     def _forward_to_external_api(self, message):
#         """
#         POST the reply payload to the URL stored in ir.config_parameter.

#         Config keys (set via Settings → Technical → Parameters):
#             zencore_helpdesk.external_api_url   (required)
#             zencore_helpdesk.outbound_api_key   (optional — sent as X-API-Key)

#         Section 4: parent_message_id is always included.
#         Failures are swallowed — the chatter post must never be blocked.
#         """
#         ICP = self.env['ir.config_parameter'].sudo()
#         external_url = ICP.get_param('zencore_helpdesk.external_api_url', default=False)
#         api_key = ICP.get_param('zencore_helpdesk.outbound_api_key', default=False)

#         if not external_url:
#             _logger.warning(
#                 "[Zencore] 'zencore_helpdesk.external_api_url' is not set. "
#                 "Skipping outbound forward for ticket id=%s.",
#                 self.id,
#             )
#             return

#         # ── Section 4: resolve parent_message_id ──────────────────────────────
#         parent_message_id = message.parent_id.id if message.parent_id else None

#         payload = {
#             "ticket_id":        self.id,
#             "ticket_name":      self.name or "",
#             "message_id":       message.id,
#             "author":           message.author_id.name or "",
#             "body":             message.body or "",
#             "date":             (
#                 message.date.strftime('%Y-%m-%d %H:%M:%S')
#                 if message.date else ""
#             ),
#             "parent_message_id": parent_message_id,
#         }

#         headers = {"Content-Type": "application/json"}
#         if api_key:
#             headers["X-API-Key"] = api_key

#         try:
#             resp = requests.post(
#                 external_url,
#                 json=payload,
#                 headers=headers,
#                 timeout=10,
#             )
#             resp.raise_for_status()
#             _logger.info(
#                 "[Zencore] Forwarded message_id=%s (ticket_id=%s) → HTTP %s",
#                 message.id, self.id, resp.status_code,
#             )

#         except requests.exceptions.Timeout:
#             _logger.error(
#                 "[Zencore] Timeout forwarding message_id=%s for ticket_id=%s to '%s'.",
#                 message.id, self.id, external_url,
#             )
#         except requests.exceptions.ConnectionError as exc:
#             _logger.error(
#                 "[Zencore] Connection error forwarding message_id=%s for ticket_id=%s: %s",
#                 message.id, self.id, exc,
#             )
#         except requests.exceptions.HTTPError as exc:
#             _logger.error(
#                 "[Zencore] HTTP error forwarding message_id=%s for ticket_id=%s: %s",
#                 message.id, self.id, exc,
#             )
#         except Exception as exc:  # noqa: BLE001
#             _logger.error(
#                 "[Zencore] Unexpected error forwarding message_id=%s for ticket_id=%s: %s",
#                 message.id, self.id, exc,
#             )

#     # ──────────────────────────────────────────────────────────────────────────
#     # SECTION 5 — Lightweight portal-user notification on outbound reply.
#     # ──────────────────────────────────────────────────────────────────────────

#     def _notify_portal_user_on_reply(self):
#         """
#         Send a plain, no-thread notification email to ticket.partner_id.

#         Rules enforced:
#           - Uses mail.mail.sudo().create().send() — NOT message_post.
#           - reply_to is explicitly blanked so the user cannot reply into
#             the Odoo mail thread.
#           - The mail.template record (defined in mail_template_data.xml) is
#             used to render subject + body so admins can adjust copy in the UI.
#           - Falls back to hardcoded strings if the template is missing.
#         """
#         if not self.partner_id or not self.partner_id.email:
#             _logger.warning(
#                 "[Zencore] ticket_id=%s has no partner email. "
#                 "Skipping portal notification.",
#                 self.id,
#             )
#             return

#         subject, body_html = self._render_notification_template(
#             'zencore_helpdesk_conversion_api.mail_template_outbound_notify_portal',
#             fallback_subject="New Reply on Your Ticket #%s" % self.id,
#             fallback_body=(
#                 "<p>You have received a new reply on your ticket.</p>"
#                 "<p>Please log in to the portal to review the latest conversation.</p>"
#             ),
#         )

#         mail_values = {
#             'subject':    subject,
#             'body_html':  body_html,
#             'email_to':   self.partner_id.email,
#             'email_from': self.env.company.email or 'noreply@example.com',
#             'reply_to':   False,   # Prevent reply-to-thread
#             'auto_delete': True,
#         }

#         self._send_mail_no_thread(mail_values, context_label="portal notification")

#     # ──────────────────────────────────────────────────────────────────────────
#     # SECTION 2 (helper) — Lightweight assigned-user notification on inbound.
#     #
#     # Called from the controller (controllers/main.py) after a successful
#     # inbound chatter post.
#     # ──────────────────────────────────────────────────────────────────────────

#     def _notify_assigned_user_on_inbound(self):
#         """
#         Send a plain, no-thread notification email to ticket.user_id.

#         Same pattern as _notify_portal_user_on_reply — mail.mail only,
#         no message_post, no reply-to.
#         """
#         if not self.user_id or not self.user_id.email:
#             _logger.warning(
#                 "[Zencore] ticket_id=%s has no assigned user email. "
#                 "Skipping agent notification.",
#                 self.id,
#             )
#             return

#         subject, body_html = self._render_notification_template(
#             'zencore_helpdesk_conversion_api.mail_template_inbound_notify_agent',
#             fallback_subject="New Message on Ticket #%s" % self.id,
#             fallback_body=(
#                 "<p>You have received a new message on Ticket #%s.</p>"
#                 "<p>Please log in to Odoo to review and respond.</p>" % self.id
#             ),
#         )

#         mail_values = {
#             'subject':    subject,
#             'body_html':  body_html,
#             'email_to':   self.user_id.email,
#             'email_from': self.env.company.email or 'noreply@example.com',
#             'reply_to':   False,
#             'auto_delete': True,
#         }

#         self._send_mail_no_thread(mail_values, context_label="agent notification")

#     # ──────────────────────────────────────────────────────────────────────────
#     # Private utilities
#     # ──────────────────────────────────────────────────────────────────────────

#     def _render_notification_template(
#         self, xml_id, fallback_subject, fallback_body
#     ):
#         """
#         Attempt to render a mail.template by xml_id against this ticket record.

#         Returns (subject, body_html) tuple.
#         Falls back to the provided strings if the template is not found or
#         rendering fails.
#         """
#         try:
#             template = self.env.ref(xml_id, raise_if_not_found=False)
#             if template:
#                 # generate_email renders Jinja2 expressions in subject/body
#                 rendered = template.generate_email(
#                     self.id, fields=['subject', 'body_html']
#                 )
#                 return (
#                     rendered.get('subject', fallback_subject),
#                     rendered.get('body_html', fallback_body),
#                 )
#         except Exception as exc:  # noqa: BLE001
#             _logger.warning(
#                 "[Zencore] Could not render template '%s' for ticket_id=%s: %s. "
#                 "Using fallback.",
#                 xml_id, self.id, exc,
#             )
#         return fallback_subject, fallback_body

#     def _send_mail_no_thread(self, mail_values, context_label="notification"):
#         """
#         Create and immediately send a mail.mail record.

#         This is the ONLY sanctioned way to send emails in this module.
#         It deliberately avoids message_post to prevent chatter attachment
#         and to bypass Odoo's outbound-thread machinery (Section 1).
#         """
#         try:
#             mail = self.env['mail.mail'].sudo().create(mail_values)
#             mail.send()
#             _logger.info(
#                 "[Zencore] Sent %s to '%s' for ticket_id=%s.",
#                 context_label,
#                 mail_values.get('email_to'),
#                 self.id,
#             )
#         except Exception as exc:  # noqa: BLE001
#             _logger.error(
#                 "[Zencore] Failed to send %s for ticket_id=%s: %s",
#                 context_label, self.id, exc,
#             )

"""
zencore_helpdesk_conversion_api — helpdesk_ticket.py

Sections covered:
    1 — Suppress all outbound email from the chatter thread.
    3 — Forward assigned-user replies to an external API.
    4 — Always include parent_message_id in every outbound payload.
    5 — Send a lightweight (no-thread) notification to the portal user
        whenever the assigned user posts a reply.

Hybrid conversation design contract
─────────────────────────────────────
Every message posted to a helpdesk ticket chatter must honour one of two
cases, driven entirely by the `parent_id` kwarg passed to message_post():

    parent_id=False (or omitted)
        → Independent root message.  Appears at the top level of the
          conversation timeline in all three response modes (tree, flat,
          hybrid).  Callers use this for a new topic the user raises that
          is not a direct reply to any prior message.

    parent_id=<mail.message id>
        → Threaded reply.  Nested under its parent in tree/hybrid modes;
          appears inline (with parent_id metadata) in flat mode.  Callers
          use this when the portal user or agent explicitly replies to a
          specific message.

The controller (controllers/main.py) enforces the same contract for inbound
portal messages via the `parent_message_id` field in the POST payload.
"""

import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Suppress Odoo's outbound email for all chatter messages.
    #
    # How Odoo normally works:
    #   message_post()  →  _notify_thread()  →  _notify_thread_by_email()
    #                                         →  _notify_thread_by_inbox()
    #                                         →  push notifications, etc.
    #
    # By returning an empty dict here we stop the entire notification pipeline
    # before any mail.mail record is created for followers.  The message itself
    # is still persisted to mail.message — the chatter remains a working
    # internal audit log.
    # ──────────────────────────────────────────────────────────────────────────

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        """
        Override: suppress ALL outbound email / push / inbox notifications
        that Odoo would normally dispatch to thread followers.

        Chatter remains a read-only internal log.  Outbound notifications are
        handled explicitly by _notify_assigned_user_on_inbound() (Section 2)
        and _notify_portal_user_on_reply() (Section 5).
        """
        return {}

    def _get_allowed_message_params(self):
        """Allow Odoo's mail controller to forward reply parent_id on tickets."""
        return super()._get_allowed_message_params() | {'parent_id'}

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 + 4 + 5 — Intercept message_post.
    #
    # message_post() is the single entry-point for every chatter message in
    # Odoo.  We call super() first so the message is saved to the DB, then
    # inspect the author to decide whether to forward externally.
    #
    # Author detection logic
    # ──────────────────────
    #   External inbound (via controller) → sudo() env → author = OdooBot (uid=1)
    #     → NOT the assigned user → NO forward triggered.
    #
    #   Assigned agent posting via the Odoo UI → author = agent's partner_id
    #     → matches ticket.user_id.partner_id → forward IS triggered.
    #
    # parent_id threading
    # ───────────────────
    #   When the agent explicitly replies to a specific message in the Odoo UI,
    #   Odoo sets message.parent_id automatically.  The forward payload (Section 4)
    #   always includes parent_message_id so the external system can maintain the
    #   same thread structure on its side.
    # ──────────────────────────────────────────────────────────────────────────

    def message_post(self, **kwargs):
        """
        Override: after persisting the chatter message, check if the author is
        the ticket's assigned user.  If so:
          - Forward the full payload to the external API  (Sections 3 + 4).
          - Email a lightweight notification to the portal user  (Section 5).
        """
        requested_parent_id = kwargs.get('parent_id')
        context_parent_id = self._zencore_resolve_reply_parent_id_from_context()
        if context_parent_id and not requested_parent_id:
            kwargs['parent_id'] = context_parent_id
            requested_parent_id = context_parent_id

        message = super().message_post(**kwargs)

        # Normal posts must stay root messages. Only the explicit Zencore reply
        # context or a deliberate parent_id kwarg may create a thread relation.
        if not requested_parent_id and message.parent_id:
            message.sudo().write({'parent_id': False})

        assigned_partner_id = (
            self.user_id.partner_id.id
            if self.user_id and self.user_id.partner_id
            else False
        )

        if assigned_partner_id and message.author_id.id == assigned_partner_id:
            self._forward_to_external_api(message)     # Sections 3 + 4

        if self._zencore_is_internal_public_comment(message):
            self._notify_portal_user_on_reply()        # Section 5

        return message

    def _zencore_is_internal_public_comment(self, message):
        """True for an internal user's Send Message, false for notes/system/inbound."""
        if message.message_type != 'comment' or not message.author_id:
            return False
        mt_note = self.env.ref('mail.mt_note', raise_if_not_found=False)
        if mt_note and message.subtype_id.id == mt_note.id:
            return False
        return any(not user.share for user in message.author_id.user_ids)

    def _zencore_resolve_reply_parent_id_from_context(self):
        """Return the selected customer message id stored by the Reply button."""
        raw_parent_id = self.env.context.get('zencore_reply_parent_id')
        if not raw_parent_id:
            return False
        try:
            parent_id = int(raw_parent_id)
        except (TypeError, ValueError):
            _logger.warning(
                "[Zencore] Invalid zencore_reply_parent_id=%s. Ignoring.",
                raw_parent_id,
            )
            return False

        ticket = self[:1]
        parent_msg = self.env['mail.message'].sudo().browse(parent_id)
        if (
            not ticket
            or not parent_msg.exists()
            or parent_msg.model != 'helpdesk.ticket'
            or parent_msg.res_id != ticket.id
        ):
            _logger.warning(
                "[Zencore] Reply parent message_id=%s is not valid for ticket_id=%s. Ignoring.",
                parent_id,
                ticket.id if ticket else False,
            )
            return False
        return parent_msg.id

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 + 4 — Forward payload to external system.
    # ──────────────────────────────────────────────────────────────────────────

    def _forward_to_external_api(self, message):
        """
        POST the reply payload to the URL stored in ir.config_parameter.

        Config keys (set via Settings → Technical → Parameters):
            zencore_helpdesk.external_api_url   (required)
            zencore_helpdesk.outbound_api_key   (optional — sent as X-API-Key)

        Section 4: parent_message_id is always included.
          - Not None  → the reply is part of a thread (agent replied to a
                         specific message via the Odoo UI).
          - None      → the agent posted an independent root message.

        Failures are swallowed — the chatter post must never be blocked.
        """
        ICP          = self.env['ir.config_parameter'].sudo()
        external_url = ICP.get_param('zencore_helpdesk.external_api_url', default=False)
        api_key      = ICP.get_param('zencore_helpdesk.outbound_api_key', default=False)

        if not external_url:
            _logger.warning(
                "[Zencore] 'zencore_helpdesk.external_api_url' is not set. "
                "Skipping outbound forward for ticket id=%s.",
                self.id,
            )
            return

        # Section 4: resolve parent_message_id — null for root, int for reply
        parent_message_id = message.parent_id.id if message.parent_id else None

        payload = {
            "ticket_id":         self.id,
            "ticket_name":       self.name or "",
            "message_id":        message.id,
            "author":            message.author_id.name or "",
            "body":              message.body or "",
            "date":              (
                message.date.strftime('%Y-%m-%d %H:%M:%S')
                if message.date else ""
            ),
            # null  → agent sent an independent root message
            # int   → agent replied to a specific message (thread reply)
            "parent_message_id": parent_message_id,
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        try:
            resp = requests.post(
                external_url,
                json=payload,
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            _logger.info(
                "[Zencore] Forwarded message_id=%s (ticket_id=%s) → HTTP %s",
                message.id, self.id, resp.status_code,
            )

        except requests.exceptions.Timeout:
            _logger.error(
                "[Zencore] Timeout forwarding message_id=%s for ticket_id=%s to '%s'.",
                message.id, self.id, external_url,
            )
        except requests.exceptions.ConnectionError as exc:
            _logger.error(
                "[Zencore] Connection error forwarding message_id=%s for ticket_id=%s: %s",
                message.id, self.id, exc,
            )
        except requests.exceptions.HTTPError as exc:
            _logger.error(
                "[Zencore] HTTP error forwarding message_id=%s for ticket_id=%s: %s",
                message.id, self.id, exc,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "[Zencore] Unexpected error forwarding message_id=%s for ticket_id=%s: %s",
                message.id, self.id, exc,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Lightweight portal-user notification on outbound reply.
    # ──────────────────────────────────────────────────────────────────────────

    def _notify_portal_user_on_reply(self):
        """
        Send a plain, no-thread notification email to ticket.partner_id.

        Rules enforced:
          - Uses mail.mail.sudo().create().send() — NOT message_post.
          - reply_to is explicitly blanked so the user cannot reply into
            the Odoo mail thread.
          - The mail.template record (defined in mail_template_data.xml) is
            used to render subject + body so admins can adjust copy in the UI.
          - Falls back to hardcoded strings if the template is missing.
        """
        if not self.partner_id or not self.partner_id.email:
            _logger.warning(
                "[Zencore] ticket_id=%s has no partner email. "
                "Skipping portal notification.",
                self.id,
            )
            return

        subject, body_html = self._render_notification_template(
            'zencore_helpdesk_conversion_api.mail_template_outbound_notify_portal',
            fallback_subject="New Reply on Your Ticket #%s" % self.id,
            fallback_body=(
                "<p>You have received a new reply on your ticket.</p>"
                "<p>Please log in to the portal to review the latest conversation.</p>"
            ),
        )

        mail_values = {
            'subject':     subject,
            'body_html':   body_html,
            'email_to':    self.partner_id.email,
            'email_from':  self.env.company.email or 'noreply@example.com',
            'reply_to':    False,   # Prevent reply-to-thread
            'auto_delete': True,
        }

        self._send_mail_no_thread(mail_values, context_label="portal notification")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 (helper) — Lightweight assigned-user notification on inbound.
    #
    # Called from the controller (controllers/main.py) after a successful
    # inbound chatter post.
    # ──────────────────────────────────────────────────────────────────────────

    def _notify_assigned_user_on_inbound(self):
        """
        Send a plain, no-thread notification email to ticket.user_id.

        Same pattern as _notify_portal_user_on_reply — mail.mail only,
        no message_post, no reply-to.
        """
        if not self.user_id or not self.user_id.email:
            _logger.warning(
                "[Zencore] ticket_id=%s has no assigned user email. "
                "Skipping agent notification.",
                self.id,
            )
            return

        subject, body_html = self._render_notification_template(
            'zencore_helpdesk_conversion_api.mail_template_inbound_notify_agent',
            fallback_subject="New Message on Ticket #%s" % self.id,
            fallback_body=(
                "<p>You have received a new message on Ticket #%s.</p>"
                "<p>Please log in to Odoo to review and respond.</p>" % self.id
            ),
        )

        mail_values = {
            'subject':     subject,
            'body_html':   body_html,
            'email_to':    self.user_id.email,
            'email_from':  self.env.company.email or 'noreply@example.com',
            'reply_to':    False,
            'auto_delete': True,
        }

        self._send_mail_no_thread(mail_values, context_label="agent notification")

    # ──────────────────────────────────────────────────────────────────────────
    # Private utilities
    # ──────────────────────────────────────────────────────────────────────────

    def _render_notification_template(
        self, xml_id, fallback_subject, fallback_body
    ):
        """
        Attempt to render a mail.template by xml_id against this ticket record.

        Returns (subject, body_html) tuple.
        Falls back to the provided strings if the template is not found or
        rendering fails.
        """
        try:
            template = self.env.ref(xml_id, raise_if_not_found=False)
            if template:
                rendered = template.generate_email(
                    self.id, fields=['subject', 'body_html']
                )
                return (
                    rendered.get('subject',   fallback_subject),
                    rendered.get('body_html', fallback_body),
                )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "[Zencore] Could not render template '%s' for ticket_id=%s: %s. "
                "Using fallback.",
                xml_id, self.id, exc,
            )
        return fallback_subject, fallback_body

    def _send_mail_no_thread(self, mail_values, context_label="notification"):
        """
        Create and immediately send a mail.mail record.

        This is the ONLY sanctioned way to send emails in this module.
        It deliberately avoids message_post to prevent chatter attachment
        and to bypass Odoo's outbound-thread machinery (Section 1).
        """
        try:
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
            _logger.info(
                "[Zencore] Sent %s to '%s' for ticket_id=%s.",
                context_label,
                mail_values.get('email_to'),
                self.id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "[Zencore] Failed to send %s for ticket_id=%s: %s",
                context_label, self.id, exc,
            )
    
    def _thread_to_store(self, store, fields, **kwargs):
        """
        Odoo 19 store.add() forwards arbitrary kwargs to _thread_to_store.
        Known kwargs seen in practice:
            request_list=  (list of requested data sections)
            as_thread=     (bool, signals thread-mode serialisation)
        We must accept and forward ALL of them to super() without modification.
        """
        super()._thread_to_store(store, fields, **kwargs)   # forward everything
        for ticket in self:
            store.add(ticket, {
                'zencore_assigned_partner_id': (
                    ticket.user_id.partner_id.id
                    if ticket.user_id and ticket.user_id.partner_id
                    else False
                ),
            })