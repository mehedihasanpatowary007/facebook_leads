# -*- coding: utf-8 -*-

from odoo import api, models
from odoo.fields import Domain


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def _timesheet_get_portal_domain(self):
        """
        Override Odoo's default portal domain so that BOTH portal users and
        internal users always see /my/timesheets — even when no timesheet
        entries exist yet.

        ROOT CAUSE
        ----------
        Odoo's stock portal-user domain is:

            (message_partner_ids child_of commercial_partner_id
             OR partner_id child_of commercial_partner_id)
            AND project_id.privacy_visibility in ['invited_users', 'portal']

        `message_partner_ids` on an analytic line is computed from the
        followers of the related task and project.  A portal user becomes a
        follower of a task only AFTER the first timesheet entry is created
        (Odoo's _message_auto_subscribe machinery fires on create).

        Before that first entry:
          • the follower record does not exist
          • message_partner_ids is empty for every timesheet line
          • the domain returns 0 rows
          • _prepare_home_portal_values sets timesheet_count = 0
          • Odoo's portal home template hides the "Timesheets" card
            when timesheet_count == 0
          • /my/timesheets shows "There are no timesheets" instead of
            the creation form

        FIX
        ---
        Replace the follower-based check with an assignment-based check:
        show timesheets whose task lists the portal user in user_ids
        (Assignees), OR whose project lists the portal user in
        portal_user_ids (the custom field from this module).

        Both branches still guard on privacy_visibility so private /
        employees-only projects are never exposed.
        """
        user = self.env.user

        # Internal users: keep Odoo's standard ORM rule computation unchanged.
        if user.has_group('hr_timesheet.group_hr_timesheet_user'):
            return self.env['ir.rule']._compute_domain(self._name)

        # Portal users: own entries only, scoped to their assignments.
        # Adding user_id = user.id ensures a portal user never sees another
        # user's timesheet entries, even on a shared project or task.

        # Branch A – user is assigned to the task that owns the timesheet line.
        assigned_via_task = (
            Domain('user_id', '=', user.id)
            & Domain('task_id.user_ids', 'in', [user.id])
            & Domain('project_id.allow_timesheets', '=', True)
            & Domain('project_id.privacy_visibility', 'in', ['invited_users', 'portal'])
        )

        # Branch B – user is in project.portal_user_ids (project-level entry,
        # no task assignment required).
        assigned_via_project = (
            Domain('user_id', '=', user.id)
            & Domain('project_id.portal_user_ids', 'in', [user.id])
            & Domain('project_id.allow_timesheets', '=', True)
            & Domain('project_id.privacy_visibility', 'in', ['invited_users', 'portal'])
        )

        return Domain('project_id', '!=', False) & (
            assigned_via_task | assigned_via_project
        )
