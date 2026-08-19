from odoo import models, api, SUPERUSER_ID


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):

        # Skip restriction for superuser
        if self.env.uid != SUPERUSER_ID:
            user = self.env.user
            is_salesman_only = (
                user.has_group('sales_team.group_sale_salesman')
                and not user.has_group('sales_team.group_sale_salesman_all_leads')
                and not user.has_group('sales_team.group_sale_manager')
            )
            if is_salesman_only:
                domain = [('user_id', '=', user.id)] + list(domain)

        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
    




    @api.model
    def message_new(self, msg_dict, custom_values=None):

        if custom_values is None:
            custom_values = {}

        # course_id is the field name in my custom module
        custom_values['course_id'] = 'Admission Mail'

        # Search if 'Admission Mail' source already exists
        source = self.env['utm.source'].search(
            [('name', '=', 'Admission Mail')], limit=1
        )

        # If not found, create it automatically
        if not source:
            source = self.env['utm.source'].create({'name': 'Admission Mail'})

        custom_values['source_id'] = source.id

        return super().message_new(msg_dict, custom_values)