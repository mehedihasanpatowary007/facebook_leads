{
    "name": "Helpdesk REST API",
    "version": "19.0.1.0.0",
    "category": "Services/Helpdesk",  # ✅ ADDED
    "summary": "REST API for Helpdesk Ticket Creation",  # ✅ ADDED
    "description": """
        REST API Integration for Helpdesk
        ==================================
        * Create helpdesk tickets via REST API
        * Public endpoint for external integrations
        * Automatic partner creation/matching
    """,  # ✅ ADDED
    "author": "Your Company",  # ✅ ADDED
    "website": "https://www.yourcompany.com",  # ✅ ADDED
    "license": "LGPL-3",  # ✅ ADDED
    "depends": [
        "base",
        "helpdesk",
        "mail",
    ],
    "data": [
        "views/helpdesk_ticket_extended_views.xml"
    ],  # ✅ ADDED: Empty data list for future security rules
    "installable": True,
    "application": False,
    "auto_install": False,  # ✅ ADDED
}