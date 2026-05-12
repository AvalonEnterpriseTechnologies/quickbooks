from odoo import api, models


class QBBalanceReconciliation(models.AbstractModel):
    _name = 'qb.balance.reconciliation'
    _description = 'QuickBooks Balance Reconciliation'

    @api.model
    def run_for_all_companies(self):
        configs = self.env['quickbooks.config'].search([('state', '=', 'connected')])
        for config in configs:
            self.run_for_company(config.company_id)

    @api.model
    def run_for_company(self, company):
        variances = self.env['qb.balance.variance'].sudo().search([
            ('company_id', '=', company.id),
        ])
        for variance in variances:
            variance.write({
                'odoo_amount': self._account_balance(
                    company, variance.account_id, variance.period_end,
                ) if variance.account_id else variance.odoo_amount,
            })
            threshold = self._threshold(company)
            variance.threshold_breached = abs(variance.variance or 0.0) > threshold

    def _account_balance(self, company, account, period_end):
        lines = self.env['account.move.line'].sudo().search([
            ('company_id', '=', company.id),
            ('account_id', '=', account.id),
            ('date', '<=', period_end),
            ('parent_state', '=', 'posted'),
            ('move_id.qb_do_not_sync', '=', False),
        ])
        return sum(lines.mapped('balance'))

    def _threshold(self, company):
        config = self.env['quickbooks.config'].sudo().search([
            ('company_id', '=', company.id),
        ], limit=1)
        return getattr(config, 'balance_variance_threshold', 0.01) or 0.01
