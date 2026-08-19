# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk Student REST API',
    'version': '19.0.1.0.0',
    'summary': 'REST API for student helpdesk ticket access',
    'description': """
        Provides REST API endpoints for students to:
        - List their helpdesk tickets (ticket ref, create date, status, subject)
        - View a single ticket detail (status, date, team, description, subject,
          communication history excluding system creation log, attachments)
    """,
    'category': 'Helpdesk',
    'author': 'Your Company',
    'website': 'https://yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'helpdesk',
        'mail',
        'portal',
    ],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
