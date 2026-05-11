from odoo import fields, models


class QuickbooksWorkersCompClass(models.Model):
    _name = 'quickbooks.workers.comp.class'
    _description = 'QuickBooks Workers Compensation Class'
    _order = 'code'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    description = fields.Text()
    jurisdiction = fields.Char()
    base_rate = fields.Float(
        help='Manual local estimate. QuickBooks does not expose workers comp class '
             'rates as a public API resource.',
    )
    active = fields.Boolean(default=True)
    source = fields.Selection(
        [('manual', 'Manual'), ('report', 'QBO Report Snapshot')],
        default='manual',
        required=True,
    )
    last_report_snapshot_id = fields.Many2one('quickbooks.report.snapshot')

    _workers_comp_code_uniq = models.Constraint(
        'unique(company_id, code)',
        'Workers comp class code must be unique per company.',
    )
