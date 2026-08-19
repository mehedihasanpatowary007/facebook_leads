# -*- coding: utf-8 -*-
{
    'name': 'Purchase Custom Quotation',
    'version': '19.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Custom Purchase Quotation with Terms & Conditions',
    'description': """
        Custom Purchase Quotation Module
        =================================
        * Add Subject field
        * Add Work Order Date field
        * Add Terms & Conditions tab
        * Custom calculation with VAT and AIT
        * Custom report template
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['purchase', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/purchase_order_views.xml',
        'report/purchase_reports.xml',
        'views/report_purchase_quotation.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}