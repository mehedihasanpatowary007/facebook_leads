# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    wub_ipcalling_enabled = fields.Boolean(
        string='Enable WUB IP Calling',
        config_parameter='zencore_wub_ipcalling.enabled',
        default=True,
    )
    wub_ipcalling_base_url = fields.Char(
        string='Base URL',
        config_parameter='zencore_wub_ipcalling.base_url',
        default='https://worlduni.ihelpbd.com',
        help='Example: https://worlduni.ihelpbd.com',
    )
    wub_ipcalling_endpoint_path = fields.Char(
        string='Endpoint Path',
        config_parameter='zencore_wub_ipcalling.endpoint_path',
        default='/wub/api/click_to_call.php',
        help='Example: /wub/api/click_to_call.php',
    )
    wub_ipcalling_authorization = fields.Char(
        string='Authorization Key',
        config_parameter='zencore_wub_ipcalling.authorization',
        default='iHelpBD@Authorization@',
        help='Value sent in the Authorization request header.',
    )
    wub_ipcalling_timeout = fields.Integer(
        string='Request Timeout (seconds)',
        config_parameter='zencore_wub_ipcalling.timeout',
        default=15,
        help='Maximum time Odoo will wait for the external API response.',
    )
    wub_ipcalling_request_format = fields.Selection(
        selection=[
            ('auto', 'Auto: JSON then Form'),
            ('json', 'JSON only'),
            ('form', 'Form URL Encoded only'),
        ],
        string='Request Format',
        config_parameter='zencore_wub_ipcalling.request_format',
        default='auto',
        help='Use Auto for this API: Odoo first sends JSON as documented, then retries as form-urlencoded if the provider returns a method/body-format error.',
    )
