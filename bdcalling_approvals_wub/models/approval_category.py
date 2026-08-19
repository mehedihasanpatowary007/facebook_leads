from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ApprovalCategory(models.Model):
    _inherit = 'approval.category'

    approval_type = fields.Selection(
        selection_add=[('internal_requisition', 'Internal Requisition')],
        ondelete={'internal_requisition': 'set null'},
    )

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        help="Warehouse to use for internal transfers.",
    )

    operation_type_id = fields.Many2one(
        'stock.picking.type',
        string='Operation Type',
        domain="[('code', '=', 'internal'), ('warehouse_id', '=', warehouse_id)]",
        help="Must be an Internal Transfer operation type.",
    )

    location_src_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        domain="[('usage', 'in', ['internal', 'transit'])]",
    )

    location_dest_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        domain="[('usage', 'in', ['internal', 'transit'])]",
    )

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id:
            self.operation_type_id = self.warehouse_id.int_type_id
            self.location_src_id = self.warehouse_id.int_type_id.default_location_src_id
            self.location_dest_id = self.warehouse_id.int_type_id.default_location_dest_id
        else:
            self.operation_type_id = False
            self.location_src_id = False
            self.location_dest_id = False

    @api.onchange('operation_type_id')
    def _onchange_operation_type_id(self):
        if self.operation_type_id:
            self.location_src_id = self.operation_type_id.default_location_src_id
            self.location_dest_id = self.operation_type_id.default_location_dest_id

    @api.constrains('approval_type', 'operation_type_id')
    def _check_internal_operation_type(self):
        for rec in self:
            if rec.approval_type == 'internal_requisition' and rec.operation_type_id:
                if rec.operation_type_id.code != 'internal':
                    raise ValidationError(
                        _("Operation Type must be of type 'Internal' for Internal Requisition categories.")
                    )
