# -*- coding: utf-8 -*-
"""
Auto-remove follower when a user is unassigned from a task.

Odoo's default behaviour adds every assigned user as a follower when they
are added to user_ids, but never removes them when they are removed.
This override makes the unsubscribe symmetric with the subscribe.
"""
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def write(self, vals):
        # Capture old assignees before the write, only when user_ids changes.
        if 'user_ids' in vals:
            old_user_ids_map = {task.id: set(task.user_ids.ids) for task in self}

        result = super().write(vals)

        if 'user_ids' in vals:
            for task in self:
                old_users = old_user_ids_map.get(task.id, set())
                new_users = set(task.user_ids.ids)
                removed_user_ids = old_users - new_users
                if not removed_user_ids:
                    continue
                removed_partners = (
                    self.env['res.users'].sudo()
                    .browse(list(removed_user_ids))
                    .mapped('partner_id')
                    .ids
                )
                if removed_partners:
                    task.sudo().message_unsubscribe(partner_ids=removed_partners)
                    _logger.info(
                        "Task %s (%s): unsubscribed partners %s after user removal",
                        task.id, task.name, removed_partners,
                    )
        return result
