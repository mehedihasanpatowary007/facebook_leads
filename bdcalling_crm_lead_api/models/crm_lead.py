# from odoo import models, fields

# class CrmLeadInherit(models.Model):
#     _inherit = 'crm.lead'

#     course = fields.Selection(
#         selection=[
#             ('bba', 'BBA'),
#             ('bsc_textile', 'B Sc in Textile Engg.'),
#             ('bsc_mechanical', 'B Sc in Mechanical Engg.'),
#             ('bsc_cse', 'B Sc in CSE'),
#             ('bsc_civil', 'B Sc in Civil Engg.'),
#             ('bsc_eee', 'B Sc in EEE'),
#             ('pharmacy', 'Pharmacy'),
#             ('fashion_design', 'Bachelor of Fashion Design and Apparel Technology'),
#             ('media_studies', 'Bachelor of Media Studies and Journalism'),
#             ('ba_english', 'Bachelor of Arts in English'),
#             ('ma_english', 'Master of Arts in English'),
#             ('law', 'Bachelor of Law'),
#             ('tourism', 'Bachelor of Tourism and Hospitality Management'),
#             ('auto_engineering', 'B.Sc. in Automobile Engineering'),
#             ('architecture', 'Bachelor of Architecture'),
#             ('msc_cyber', 'M.Sc. in Cyber Security'),
#             ('meng_telecom', 'M.Engg. in Telecommunication Engineering'),
#             ('mechatronics', 'B.Sc. in Mechatronics Engineering'),
#             ('mpharm', 'Master of Pharmacy (M Pharm)'),
#             ('apparel_mfg', 'B.Sc. in Apparel Manufacturing Engineering'),
#             ('mba', 'Master of Business Administration (MBA)'),
#             ('mph', 'Master of Public Health (MPH)'),
#         ],
#         string='Course',
#         required=True
#     )

#     specialization = fields.Selection(
#         selection=[
#             ('general', 'General'),
#             ('major', 'Major'),
#             ('minor', 'Minor'),
#         ],
#         string='Specialization',
#     )

#     query = fields.Text(string='Query', tracking=True)




from odoo import models, fields, api

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    course_id = fields.Char(string="Course")
    specialization_id = fields.Char(string="Specialization" )
    query = fields.Text(string='Query', tracking=True)








