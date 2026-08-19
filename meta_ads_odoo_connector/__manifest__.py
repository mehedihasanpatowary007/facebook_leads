# -*- coding: utf-8 -*-
{
    'name': 'Meta Ads Odoo Connector',
    'summary': 'Meta/Facebook Ads backend integration for CRM, Sales attribution, Insights and Conversions API.',
    'description': """
Meta Ads Odoo Connector
=======================
Safe production-oriented starter connector for Odoo 19.

Main features:
- Meta connection configuration
- Ad Account, Campaign, Ad Set, Ad, Creative models
- Ads Insights daily storage
- CRM lead attribution fields
- Conversion API event queue
- API logs and retry-ready sync foundation

This module intentionally does not create or modify live Meta campaigns in v1.
Start with read/reporting, lead attribution and conversion queue first.
    """,
    'version': '19.0.1.0.0',
    'category': 'Marketing',
    'author': 'Zencore Solution Limited',
    'website': 'https://www.zencoresolution.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'utm',
        'crm',
        'sale_management',
        'account',
        'website',
        'website_sale',
        'product',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/meta_ads_config_views.xml',
        'views/meta_ad_account_views.xml',
        'views/meta_campaign_views.xml',
        'views/meta_ad_set_views.xml',
        'views/meta_ad_creative_views.xml',
        'views/meta_ad_views.xml',
        'views/meta_ads_insight_views.xml',
        'views/meta_conversion_event_views.xml',
        'views/meta_lead_form_views.xml',
        'views/meta_api_log_views.xml',
        'views/crm_lead_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
