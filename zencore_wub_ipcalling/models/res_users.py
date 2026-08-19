# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    ip_calling_mail = fields.Char(
        string='IP Calling Mail',
        help=(
            'Agent email used by the external WUB/iHelpBD click-to-call API. '
            'Example: green@ihelpbd.com'
        ),
        copy=False,
    )

    @property
    def SELF_READABLE_FIELDS(self):
        fields_list = list(super().SELF_READABLE_FIELDS)
        if 'ip_calling_mail' not in fields_list:
            fields_list.append('ip_calling_mail')
        return fields_list

    @property
    def SELF_WRITEABLE_FIELDS(self):
        fields_list = list(super().SELF_WRITEABLE_FIELDS)
        if 'ip_calling_mail' not in fields_list:
            fields_list.append('ip_calling_mail')
        return fields_list
