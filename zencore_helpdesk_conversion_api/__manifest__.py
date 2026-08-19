{
    'name': 'Zencore Helpdesk Conversion API',
    'version': '19.0.1.0.0',
    'category': 'Helpdesk',
    'summary': (
        'Replaces default Helpdesk chatter email flow with '
        'an external API-based messaging bridge.'
    ),
    'description': """
        This module:
        - Disables Odoo's default outbound email from helpdesk chatter threads.
        - Exposes a public REST endpoint to receive inbound messages from an
          external portal and log them as internal chatter notes.
        - Forwards replies by the assigned user to a configured external API.
        - Sends lightweight (no-thread) email notifications to both the assigned
          agent (on inbound) and the portal user (on outbound reply).
    """,
    'author': 'Zencore',
    'depends': ['helpdesk', 'mail', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # ── 1. Styles — load first (JS may query layout) ──────────────────
            'zencore_helpdesk_conversion_api/static/src/scss/helpdesk_messenger.scss',

            # ── 2. Services — must exist before components that inject them ───
            # chat_reply_service.js is kept as a passive stub.
            # chatReply.replyMessage is never set now (we use the native
            # thread.replyingToMessage API instead), so the composer_patch.js
            # always falls through to super.sendMessage() — no behaviour change.
            'zencore_helpdesk_conversion_api/static/src/js/chat_reply_service.js',

            # ── 3. Shared reply state — selected parent id before send ──────
            'zencore_helpdesk_conversion_api/static/src/js/reply_parent_state.js',

            # ── 3. DOM patches — Thread class injection for CSS scoping ───────
            # MUST load before any message action or CSS is rendered
            'zencore_helpdesk_conversion_api/static/src/js/message_patch.js',

            # ── 4. Action registry overrides ──────────────────────────────────
            # remove_default_reply must load AFTER @mail registers "reply"
            # (guaranteed: our module depends on mail → mail loads first)
            'zencore_helpdesk_conversion_api/static/src/js/remove_default_reply.js',

            # ── 5. Custom reply action ────────────────────────────────────────
            'zencore_helpdesk_conversion_api/static/src/js/message_reply_action.js',

            # ── 6. Composer patch (passive — falls to super when no chatReply) ─
            'zencore_helpdesk_conversion_api/static/src/js/composer_patch.js',

            # ── 7. OWL templates ──────────────────────────────────────────────
            # composer_reply.xml's t-if="env.services.chatReply.replyMessage"
            # evaluates to false (replyMessage is never set now) — no render,
            # no conflict with Odoo's native reply preview.
            'zencore_helpdesk_conversion_api/static/src/xml/composer_reply.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}