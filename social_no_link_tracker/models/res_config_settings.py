# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Add a setting to disable automatic link shortening/tracking in Social Marketing posts."""

    _inherit = 'res.config.settings'

    social_disable_link_tracker = fields.Boolean(
        string='Disable Auto Link Tracking in Social Posts',
        help=(
            'When enabled, URLs you type in the Social Marketing post message are sent '
            'as-is and are NOT replaced by Odoo short/tracked links (e.g. /r/XXXXX). '
            'Disable this option to restore the default Odoo behaviour where every URL '
            'is automatically converted into a trackable short link.'
        ),
        config_parameter='social.disable_link_tracker',
    )
