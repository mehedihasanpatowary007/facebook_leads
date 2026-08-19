from odoo import models, fields

class HelpdeskTicketExtended(models.Model):
    _inherit = 'helpdesk.ticket'

    help_topic = fields.Char(string='Help Topic')

    team_id = fields.Many2one(
        'helpdesk.team', 
        string='Helpdesk Team',
        required=False,
    )
