{
    'name': 'CRM Lead API',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Custom CRM Lead API with Course and Query fields',
    'description': """
        CRM Lead API Module
        ===================
        * Add custom fields: Course, Specialization, Query
        * REST API endpoints for CRUD operations
        * Enhanced lead management
    """,
    'author': 'Anwar',
    'depends': ['crm', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        #'views/course_views.xml',
        'views/duplicate_leads.xml',
        'views/note_require.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}