{
    'name': 'CRM Round Robin Lead Assignment',
    'version': '19.0.2.0.0',
    'category': 'CRM',
    'summary': 'Distribute unassigned leads to team members via round-robin (scheduled + manual)',
    'description': """
CRM Round Robin Lead Assignment
- Automatically assigns UNASSIGNED leads to sales team members using round-robin
- Respects each team's Assignment Rules domain filter
- Runs on a configurable schedule (minutes / hours / days / weeks)
- Also works via the "Assign Leads" button on the Sales Team form
- Skips already-assigned leads (user_id is set)
- Skips inactive team members
    """,
    'author': 'Anwar',
    'depends': ['crm','bdcalling_crm_lead_api'],
    'data': [
        'security/ir.model.access.csv',
        'security/crm_lead_restriction.xml',
        'data/ir_cron.xml',
        'views/crm_team_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
