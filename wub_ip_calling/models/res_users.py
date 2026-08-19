from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    ip_calling_email = fields.Char(
        string="IP Calling Email"
    )