# -*- coding: utf-8 -*-
{
    'name': 'Zencore WUB IP Calling',
    'summary': 'CRM click-to-call integration with WUB/iHelpBD IP Calling API',
    'description': '''
Zencore WUB IP Calling
======================
Adds an IP Call button on CRM leads/opportunities, stores API call history,
and allows per-user agent email configuration for WUB/iHelpBD click-to-call.
    ''',
    'version': '19.0.1.3.0',
    'category': 'CRM',
    'author': 'Madhusudan Ray',
    'depends': [
        'base',
        'crm',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/ip_call_history_rules.xml',
        'data/ir_sequence_data.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'views/ip_call_history_views.xml',
        'views/crm_lead_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
