from odoo import fields, models


class QuickbooksHrAdvisorNote(models.Model):
    _name = 'quickbooks.hr.advisor.note'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'QuickBooks HR Advisor Reference Note'
    _order = 'create_date desc'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    name = fields.Char(required=True, tracking=True)
    category = fields.Selection(
        [
            ('policy', 'Policy'),
            ('compliance', 'Compliance'),
            ('handbook', 'Handbook'),
            ('template', 'Template'),
            ('other', 'Other'),
        ],
        default='other',
        required=True,
        tracking=True,
    )
    external_url = fields.Char(string='External HR Advisor / Mineral URL')
    notes = fields.Html()
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'quickbooks_hr_advisor_note_attachment_rel',
        'note_id',
        'attachment_id',
        string='Attachments',
    )
    api_status = fields.Selection(
        [('manual', 'Manual Only - No Public QBO API')],
        default='manual',
        required=True,
        readonly=True,
    )
