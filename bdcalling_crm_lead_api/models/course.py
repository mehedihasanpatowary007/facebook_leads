# from odoo import models, fields


# class Course(models.Model):
#     _name = 'edu.course'
#     _description = 'Course'

#     name = fields.Char(string="Course Name", required=True)
#     specialization_ids = fields.One2many(
#         'edu.course.specialization',
#         'course_id',
#         string="Specializations"
#     )




# class CourseSpecialization(models.Model):
#     _name = 'edu.course.specialization'
#     _description = 'Course Specialization'

#     name = fields.Char(string="Specialization Name")
#     course_id = fields.Many2one(
#         'edu.course',
#         string="Course",
#         required=True,
#         ondelete='cascade'
#     )




#phone and id diye search kore duplicate leads ase kina

from odoo import models, fields, api

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    duplicate_count = fields.Integer(
        string="Duplicate Leads",
        compute="_compute_duplicate_count"
    )

    def _compute_duplicate_count(self):
        for lead in self:
            if lead.phone:
                duplicates = self.search([
                    ('phone', '=', lead.phone),
                    ('id', '!=', lead.id)
                ])
                lead.duplicate_count = len(duplicates)
            else:
                lead.duplicate_count = 0

    def action_view_duplicates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Duplicate Leads',
            'res_model': 'crm.lead',
            'view_mode': 'list,form',
            'domain': [
                ('phone', '=', self.phone),
                ('id', '!=', self.id)
            ],
            'context': {'create': False}
        }