# -*- coding: utf-8 -*-
{
    'name': 'Zencore WUB Hangup',
    'summary': 'Hang up active WUB/iHelpBD IP calls from CRM',
    'description': '''
Zencore WUB Hangup
==================
Adds an optional Hang Up action to Zencore WUB IP Calling. Hangup API
requests and responses are recorded in the existing IP call history.
    ''',
    'version': '19.0.1.0.1',
    'category': 'CRM',
    'author': 'Madhusudan Ray',
    'depends': [
        'zencore_wub_ipcalling',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/ip_call_history_views.xml',
        'views/crm_lead_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}