from odoo import models, fields, api, _
from odoo.exceptions import UserError
import markupsafe


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Internal Transfer',
        readonly=True,
        copy=False,
    )

    is_internal_requisition = fields.Boolean(
        compute='_compute_is_internal_requisition',
        store=True,
    )

    # Track whether transfer has been created — used to lock product lines
    transfer_created = fields.Boolean(
        string='Transfer Created',
        default=False,
        readonly=True,
        copy=False,
    )

    @api.depends('category_id', 'category_id.approval_type')
    def _compute_is_internal_requisition(self):
        for rec in self:
            rec.is_internal_requisition = (
                rec.category_id.approval_type == 'internal_requisition'
            )

    def action_create_internal_transfer(self):
        self.ensure_one()

        if self.request_status != 'approved':
            raise UserError(_("Only fully approved requests can create a transfer."))
        if not self.is_internal_requisition:
            raise UserError(_("This action is only available for Internal Requisition requests."))
        if self.picking_id:
            raise UserError(_("A transfer already exists: %s") % self.picking_id.name)
        if not self.product_line_ids:
            raise UserError(_("Please add at least one product line before creating a transfer."))

        category = self.category_id
        picking_type = category.operation_type_id

        if not picking_type:
            warehouse = category.warehouse_id or self.env['stock.warehouse'].search(
                [('company_id', '=', self.company_id.id)], limit=1
            )
            if not warehouse or not warehouse.int_type_id:
                raise UserError(_("Internal operation type not configured in the Approval Category."))
            picking_type = warehouse.int_type_id

        location_src = category.location_src_id or picking_type.default_location_src_id
        location_dest = category.location_dest_id or picking_type.default_location_dest_id

        if not location_src or not location_dest:
            raise UserError(_("Source/Destination locations not configured in the Approval Category."))

        # Build picking vals — include partner if set on request
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'origin': self.name,
            'company_id': self.company_id.id,
        }

        # pass contact/partner to the transfer if set
        if self.partner_id:
            picking_vals['partner_id'] = self.partner_id.id

        picking = self.env['stock.picking'].sudo().create(picking_vals)

        for line in self.product_line_ids:
            if not line.product_id:
                continue
            self.env['stock.move'].sudo().create({
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_id.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': self.company_id.id,
            })

        self.picking_id = picking.id
        # lock product lines after transfer is created
        self.transfer_created = True

        self.message_post(
            body=markupsafe.Markup(
                "Internal Transfer <b>%s</b> has been created from this requisition."
            ) % picking.name,
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Transfer'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_internal_transfer(self):
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_("No internal transfer found for this requisition."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Transfer'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }