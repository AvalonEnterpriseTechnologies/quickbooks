from odoo import fields, models


class QuickbooksBankRule(models.Model):
    _name = 'quickbooks.bank.rule'
    _description = 'QuickBooks Bank Rule Mirror'
    _order = 'priority desc, name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    priority = fields.Integer(default=10)
    conditions_json = fields.Json(
        help='Local mirror of QBO-style bank rule conditions. QBO does not expose '
             'bank rules through a public CRUD API.',
    )
    target_account_id = fields.Many2one('account.account', ondelete='set null')
    target_payee_id = fields.Many2one('res.partner', ondelete='set null')
    reconcile_model_id = fields.Many2one(
        'account.reconcile.model',
        string='Odoo Reconciliation Model',
        ondelete='set null',
    )
    api_status = fields.Selection(
        [('manual', 'Manual Only - No Public QBO API')],
        default='manual',
        required=True,
        readonly=True,
    )
