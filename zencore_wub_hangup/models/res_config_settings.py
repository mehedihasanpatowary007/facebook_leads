# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    wub_ipcalling_hangup_endpoint_path = fields.Char(
        string='Hangup Endpoint Path',
        config_parameter='zencore_wub_ipcalling.hangup_endpoint_path',
        default='/wub/api/call_hangup.php',
        help='Example: /wub/api/call_hangup.php',
    )
