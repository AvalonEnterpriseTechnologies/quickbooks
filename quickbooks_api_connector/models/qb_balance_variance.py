from odoo import api, fields, models


class QbBalanceVariance(models.Model):
    _name = 'qb.balance.variance'
    _description = 'QuickBooks / Odoo Balance Variance'
    _order = 'period_end desc, abs_variance desc'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    account_id = fields.Many2one('account.account', index=True, ondelete='cascade')
    label = fields.Char(required=True)
    report_type = fields.Char(index=True)
    period_start = fields.Date(index=True)
    period_end = fields.Date(required=True, index=True)
    accounting_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        default='Accrual',
        required=True,
    )
    qb_amount = fields.Monetary(currency_field='currency_id')
    odoo_amount = fields.Monetary(currency_field='currency_id')
    variance = fields.Monetary(
        currency_field='currency_id',
        compute='_compute_variance',
        store=True,
    )
    abs_variance = fields.Monetary(
        currency_field='currency_id',
        compute='_compute_variance',
        store=True,
    )
    variance_pct = fields.Float(compute='_compute_variance', store=True)
    threshold_breached = fields.Boolean(index=True)
    raw_json = fields.Json()
    fetched_at = fields.Datetime(default=fields.Datetime.now, required=True)
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends('qb_amount', 'odoo_amount')
    def _compute_variance(self):
        for rec in self:
            variance = (rec.odoo_amount or 0.0) - (rec.qb_amount or 0.0)
            rec.variance = variance
            rec.abs_variance = abs(variance)
            rec.variance_pct = variance / rec.qb_amount if rec.qb_amount else 0.0
