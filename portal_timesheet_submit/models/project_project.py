# -*- coding: utf-8 -*-
from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    portal_user_ids = fields.Many2many(
        'res.users',
        'project_portal_user_rel',
        'project_id',
        'user_id',
        string='Assign Portal Users',
        help='Portal users assigned to this project who can log time from the website portal.',
        domain=[('share', '=', True), ('active', '=', True)],
    )


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Odoo default domain on user_ids is:
    #   [('share', '=', False), ('active', '=', True)]
    # which excludes portal users (share=True).
    # We change it to show BOTH internal (share=False) AND portal (share=True)
    # users, but still exclude public/inactive users.
    # Public users have no active res.users record with share=True active group,
    # so domain [('active','=',True)] already excludes them.
    # We set share in [False, True] which means: internal OR portal, NOT public.
    user_ids = fields.Many2many(
        domain=[('active', '=', True), ('share', 'in', [False, True])],
    )
