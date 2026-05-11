from .common import QuickbooksTestCommon


class TestBalanceReconciliation(QuickbooksTestCommon):

    def test_account_balance_variance_is_recorded(self):
        account = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Variance Cash',
            'code': '1998',
            'account_type': 'asset_cash',
            'qb_account_id': 'ACCT1',
        })
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'TrialBalance',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 1,
        })
        self.env['quickbooks.account.balance'].create({
            'company_id': self.company.id,
            'account_id': account.id,
            'qb_account_id': 'ACCT1',
            'account_name': account.name,
            'report_type': 'TrialBalance',
            'period_end': '2026-01-31',
            'balance': 25.0,
            'debit_balance': 25.0,
            'currency_id': self.company.currency_id.id,
            'snapshot_id': snapshot.id,
        })

        self.env['qb.balance.reconciliation'].reconcile_snapshot(snapshot)

        variance = self.env['quickbooks.balance.variance'].search([
            ('snapshot_id', '=', snapshot.id),
        ], limit=1)
        self.assertEqual(variance.account_id, account)
        self.assertEqual(variance.qb_amount, 25.0)
        self.assertEqual(variance.odoo_amount, 0.0)
        self.assertEqual(variance.variance, -25.0)
        self.assertTrue(variance.threshold_breached)

