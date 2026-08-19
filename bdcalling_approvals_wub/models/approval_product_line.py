from odoo import models, fields, api, _
from odoo.tools import html_escape
from odoo.exceptions import UserError
import markupsafe


class ApprovalProductLine(models.Model):
    _inherit = 'approval.product.line'

    product_id = fields.Many2one('product.product', tracking=True)
    description = fields.Text(tracking=True)
    quantity = fields.Float(tracking=True)
    vendor_id = fields.Many2one('res.partner', tracking=True)
    price_unit = fields.Float(tracking=True)

    def _post_message(self, request, body_str):
        request.message_post(
            body=markupsafe.Markup(body_str),
            subtype_xmlid='mail.mt_note',
        )

    def _check_transfer_lock(self):
        """Requirement 1: Block edits after transfer is created."""
        for line in self:
            req = line.approval_request_id
            if req and req.is_internal_requisition and req.transfer_created:
                raise UserError(
                    _("Product lines cannot be modified after the Internal Transfer has been created.")
                )

    #  CREATE 
    @api.model_create_multi
    def create(self, vals_list):
        # Check lock for existing requests (new lines after transfer created)
        for vals in vals_list:
            req_id = vals.get('approval_request_id')
            if req_id:
                req = self.env['approval.request'].browse(req_id)
                if req.is_internal_requisition and req.transfer_created:
                    raise UserError(
                        _("Product lines cannot be added after the Internal Transfer has been created.")
                    )

        records = super().create(vals_list)
        for line in records:
            if not line.approval_request_id:
                continue
            is_internal = line.approval_request_id.is_internal_requisition
            product_name = html_escape(line.product_id.display_name or '')
            uom_name = html_escape(line.product_id.uom_id.name or '') if line.product_id else ''

            if is_internal:
                body = (
                    f"<b>Product Added</b><br/>"
                    f"Product: <b>{product_name}</b><br/>"
                    f"Quantity: <b>{line.quantity} {uom_name}</b>"
                )
            else:
                vendor = html_escape(line.vendor_id.name if line.vendor_id else 'No Vendor')
                body = (
                    f"<b>Product Added</b><br/>"
                    f"Product: <b>{product_name}</b><br/>"
                    f"Quantity: <b>{line.quantity}</b><br/>"
                    f"Vendor: <b>{vendor}</b>"
                )
            self._post_message(line.approval_request_id, body)
        return records

    #  WRITE 
    def write(self, vals):
        # block edits after transfer created
        self._check_transfer_lock()

        for line in self:
            is_internal = line.approval_request_id.is_internal_requisition
            old_product = html_escape(line.product_id.display_name or '')
            old_quantity = line.quantity
            old_description = html_escape(line.description or '')
            old_vendor = html_escape(line.vendor_id.name if line.vendor_id else 'No Vendor')
            old_price = line.price_unit

            super(ApprovalProductLine, line).write(vals)

            if not line.approval_request_id:
                continue

            change_lines = []

            if 'product_id' in vals:
                new_product = html_escape(line.product_id.display_name or '')
                product_header = f"Product: <b>{old_product} → {new_product}</b>"
            else:
                product_header = f"Product: <b>{old_product}</b>"

            if 'quantity' in vals:
                change_lines.append(f"Quantity: <b>{old_quantity} → {line.quantity}</b>")

            if 'description' in vals:
                new_desc = html_escape(line.description or '')
                change_lines.append(f"Description: <b>{old_description} → {new_desc}</b>")

            if not is_internal and 'vendor_id' in vals:
                new_vendor = html_escape(line.vendor_id.name if line.vendor_id else 'No Vendor')
                change_lines.append(f"Vendor: <b>{old_vendor} → {new_vendor}</b>")

            if not is_internal and 'price_unit' in vals:
                change_lines.append(f"Unit Price: <b>{old_price} → {line.price_unit}</b>")

            if 'product_id' in vals or change_lines:
                changes = "<br/>".join(change_lines)
                body = f"<b>Product Updated</b><br/>{product_header}"
                if changes:
                    body += f"<br/>{changes}"
                self._post_message(line.approval_request_id, body)

        return True

    #  DELETE 
    def unlink(self):
        # block delete after transfer created
        self._check_transfer_lock()

        for line in self:
            if not line.approval_request_id:
                continue
            is_internal = line.approval_request_id.is_internal_requisition
            product_name = html_escape(line.product_id.display_name or '')

            if is_internal:
                body = (
                    f"<b>Product Removed</b><br/>"
                    f"Product: <b>{product_name}</b><br/>"
                    f"Quantity: <b>{line.quantity}</b>"
                )
            else:
                vendor = html_escape(line.vendor_id.name if line.vendor_id else 'No Vendor')
                body = (
                    f"<b>Product Removed</b><br/>"
                    f"Product: <b>{product_name}</b><br/>"
                    f"Quantity: <b>{line.quantity}</b><br/>"
                    f"Vendor: <b>{vendor}</b>"
                )
            self._post_message(line.approval_request_id, body)
        return super().unlink()

