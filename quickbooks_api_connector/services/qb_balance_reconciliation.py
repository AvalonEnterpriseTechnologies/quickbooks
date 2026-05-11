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
        snapshots = self.env['quickbooks.report.snapshot'].sudo().search([
            ('company_id', '=', company.id),
            ('report_type', 'in', [
                'BalanceSheet',
                'TrialBalance',
                'AgedReceivables',
                'AgedReceivableDetail',
                'AgedPayables',
                'AgedPayableDetail',
                'InventoryValuationSummary',
            ]),
        ], order='period_end desc, fetched_at desc', limit=24)
        for snapshot in snapshots:
            self.reconcile_snapshot(snapshot)

    @api.model
    def reconcile_snapshot(self, snapshot):
        Variance = self.env['quickbooks.balance.variance'].sudo()
        Variance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        if snapshot.report_type in ('BalanceSheet', 'TrialBalance'):
            self._reconcile_account_balances(snapshot)
        elif snapshot.report_type in (
            'AgedReceivables',
            'AgedReceivableDetail',
            'AgedPayables',
            'AgedPayableDetail',
        ):
            self._reconcile_partner_balances(snapshot)
        elif snapshot.report_type == 'InventoryValuationSummary':
            self._reconcile_inventory_balances(snapshot)

    def _reconcile_account_balances(self, snapshot):
        balances = self.env['quickbooks.account.balance'].sudo().search([
            ('snapshot_id', '=', snapshot.id),
        ])
        for balance in balances:
            account = balance.account_id
            if not account:
                continue
            odoo_amount = self._account_balance(snapshot.company_id, account, snapshot.period_end)
            self._create_variance(
                snapshot=snapshot,
                source=balance,
                label=balance.account_name,
                qb_amount=balance.balance,
                odoo_amount=odoo_amount,
                account=account,
            )

    def _reconcile_partner_balances(self, snapshot):
        balances = self.env['quickbooks.partner.balance'].sudo().search([
            ('snapshot_id', '=', snapshot.id),
        ])
        for balance in balances:
            partner = balance.partner_id
            if not partner:
                continue
            odoo_amount = self._partner_balance(
                snapshot.company_id, partner, balance.kind, snapshot.period_end,
            )
            self._create_variance(
                snapshot=snapshot,
                source=balance,
                label=balance.partner_name,
                qb_amount=balance.total,
                odoo_amount=odoo_amount,
                partner=partner,
            )

    def _reconcile_inventory_balances(self, snapshot):
        balances = self.env['quickbooks.inventory.balance'].sudo().search([
            ('snapshot_id', '=', snapshot.id),
        ])
        for balance in balances:
            product = balance.product_id
            if not product:
                continue
            odoo_amount = self._inventory_value(snapshot.company_id, product)
            self._create_variance(
                snapshot=snapshot,
                source=balance,
                label=balance.product_name,
                qb_amount=balance.value,
                odoo_amount=odoo_amount,
                product=product,
            )

    def _account_balance(self, company, account, period_end):
        lines = self.env['account.move.line'].sudo().search([
            ('company_id', '=', company.id),
            ('account_id', '=', account.id),
            ('date', '<=', period_end),
            ('parent_state', '=', 'posted'),
            ('move_id.qb_do_not_sync', '=', False),
        ])
        return sum(lines.mapped('balance'))

    def _partner_balance(self, company, partner, kind, period_end):
        account_types = (
            ['asset_receivable'] if kind == 'customer' else ['liability_payable']
        )
        lines = self.env['account.move.line'].sudo().search([
            ('company_id', '=', company.id),
            ('partner_id', '=', partner.id),
            ('account_id.account_type', 'in', account_types),
            ('date', '<=', period_end),
            ('parent_state', '=', 'posted'),
            ('move_id.qb_do_not_sync', '=', False),
        ])
        return sum(lines.mapped('balance'))

    def _inventory_value(self, company, product):
        try:
            Quant = self.env['stock.quant'].sudo()
        except KeyError:
            return 0.0
        quants = Quant.search([
            ('product_id', '=', product.id),
            ('company_id', 'in', [company.id, False]),
        ])
        qty = sum(quants.mapped('quantity'))
        return qty * (product.standard_price or 0.0)

    def _create_variance(
        self, snapshot, source, label, qb_amount, odoo_amount,
        account=False, partner=False, product=False,
    ):
        qb_amount = qb_amount or 0.0
        odoo_amount = odoo_amount or 0.0
        variance = odoo_amount - qb_amount
        threshold = self._threshold(snapshot.company_id)
        variance_pct = (variance / qb_amount * 100.0) if qb_amount else 0.0
        self.env['quickbooks.balance.variance'].sudo().create({
            'company_id': snapshot.company_id.id,
            'snapshot_id': snapshot.id,
            'source_model': source._name,
            'source_id': source.id,
            'account_id': account.id if account else False,
            'partner_id': partner.id if partner else False,
            'product_id': product.id if product else False,
            'label': label,
            'period_end': snapshot.period_end,
            'qb_amount': qb_amount,
            'odoo_amount': odoo_amount,
            'variance': variance,
            'abs_variance': abs(variance),
            'variance_pct': variance_pct,
            'threshold_breached': abs(variance) > threshold,
            'currency_id': snapshot.company_id.currency_id.id,
        })

    def _threshold(self, company):
        config = self.env['quickbooks.config'].sudo().search([
            ('company_id', '=', company.id),
        ], limit=1)
        return getattr(config, 'balance_variance_threshold', 0.01) or 0.01
