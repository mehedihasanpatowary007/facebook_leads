{
    'name': 'Portal Timesheet Submit',
    'version': '19.0.1.0.0',
    'category': 'Services/Timesheets',
    'summary': 'Portal users can create timesheet entries from /my/timesheets',
    'author': 'Custom Development',
    'depends': ['hr_timesheet', 'portal', 'project'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_portal_user.xml',
        'views/portal_timesheet_templates.xml',
        'views/account_analytic_line_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'portal_timesheet_submit/static/src/css/portal_timesheet.css',
            'portal_timesheet_submit/static/src/js/portal_timesheet.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}