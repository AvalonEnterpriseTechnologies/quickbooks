from .common import QuickbooksTestCommon


class TestBalanceReconciliation(QuickbooksTestCommon):

    def test_account_balance_variance_is_recorded(self):
        account = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Variance Cash',
            'code': '1998',
            'account_type': 'asset_cash',
            'qb_account_id': 'ACCT1',
        })
        variance = self.env['qb.balance.variance'].create({
            'company_id': self.company.id,
            'report_type': 'TrialBalance',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'account_id': account.id,
            'label': account.name,
            'qb_amount': 25.0,
            'currency_id': self.company.currency_id.id,
        })

        self.env['qb.balance.reconciliation'].run_for_company(self.company)
        variance.invalidate_recordset()
        self.assertEqual(variance.account_id, account)
        self.assertEqual(variance.qb_amount, 25.0)
        self.assertEqual(variance.odoo_amount, 0.0)
        self.assertEqual(variance.variance, -25.0)
        self.assertTrue(variance.threshold_breached)

