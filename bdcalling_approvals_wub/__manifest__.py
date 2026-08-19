{
    "name": "Internal Requisition via Approval",
    "version": "19.0.2.0.0",
    "category": "Approvals",
    "summary": "Enable Internal Requisition Workflow in Approval Module with Stock Transfer Integration",
    "description": """
        This module extends Odoo Approvals with Internal Requisition support:
        - New Approval Type: Internal Requisition
        - Warehouse, Operation Type, Source & Destination Location configuration
        - Triggers Stock Picking (Internal Transfer) after full approval
        - Hides Create RFQ button, shows Create Transfer button
        - Approvers can modify product lines (quantity)
        - All changes tracked in chatter with full audit log
        - Smart button linking Approval Request to Stock Picking
    """,
    "author": "Anwar Hossain",
    "license": "LGPL-3",
    "depends": [
        "approvals",
        "mail",
        "stock",
        "purchase",
    ],
    "data": [
        "security/approval_security.xml",
        "views/approval_category_view.xml",
        "views/approval_request_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
