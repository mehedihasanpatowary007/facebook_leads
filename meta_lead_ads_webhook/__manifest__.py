# -*- coding: utf-8 -*-
{
    'name': 'Meta Lead Ads Webhook CRM',
    'summary': 'Real-time Meta/Facebook Lead Ads webhook integration with Odoo CRM',
    'description': '''
Real-time Meta/Facebook Lead Ads webhook integration for Odoo 19.

Features:
- Public webhook endpoint for Meta leadgen events
- Webhook verification endpoint
- Optional X-Hub-Signature-256 validation
- Webhook event audit log
- Lead queue with retry/error handling
- Fetch full lead details from Meta Graph API
- Create crm.lead records with Meta attribution
- Lead form mapping with default salesperson/team/tags
- Duplicate handling
- Manual retry and cron processing
    ''',
    'version': '19.0.1.0.0',
    'category': 'Marketing/CRM',
    'author': 'Zencore Solution Limited',
    'website': 'https://www.zencoresolution.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'crm',
        'utm',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/meta_lead_connection_views.xml',
        'views/meta_lead_form_mapping_views.xml',
        'views/meta_lead_webhook_event_views.xml',
        'views/meta_lead_queue_views.xml',
        'views/crm_lead_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}
