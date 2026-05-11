from .common import QuickbooksTestCommon


class TestPostOpeningBalances(QuickbooksTestCommon):

    def test_trial_balance_snapshot_posts_opening_move(self):
        cash = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Opening Cash',
            'code': '1090',
            'account_type': 'asset_cash',
            'qb_account_id': '10',
        })
        revenue = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Opening Revenue',
            'code': '4090',
            'account_type': 'income',
            'qb_account_id': '20',
        })
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'TrialBalance',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 2,
        })
        self.env['quickbooks.account.balance'].create({
            'company_id': self.company.id,
            'account_id': cash.id,
            'qb_account_id': '10',
            'account_name': 'Opening Cash',
            'report_type': 'TrialBalance',
            'period_end': '2026-01-31',
            'balance': 500.0,
            'debit_balance': 500.0,
            'credit_balance': 0.0,
            'currency_id': self.company.currency_id.id,
            'snapshot_id': snapshot.id,
        })
        self.env['quickbooks.account.balance'].create({
            'company_id': self.company.id,
            'account_id': revenue.id,
            'qb_account_id': '20',
            'account_name': 'Opening Revenue',
            'report_type': 'TrialBalance',
            'period_end': '2026-01-31',
            'balance': -500.0,
            'debit_balance': 0.0,
            'credit_balance': 500.0,
            'currency_id': self.company.currency_id.id,
            'snapshot_id': snapshot.id,
        })
        journal = self.env['qb.sync.journals'].ensure_general_journal(
            self.config, key='qbo:general:opening',
            name='QuickBooks Opening Balances',
        )
        equity = self.env['qb.post.opening.balances.wizard']._opening_equity_account(
            self.company,
        )
        wizard = self.env['qb.post.opening.balances.wizard'].create({
            'company_id': self.company.id,
            'as_of_date': '2026-01-31',
            'snapshot_id': snapshot.id,
            'target_journal_id': journal.id,
            'opening_equity_account_id': equity.id,
            'retained_earnings_account_id': equity.id,
            'dry_run': False,
        })

        action = wizard.action_post_opening_balances()
        move = self.env['account.move'].browse(action['res_id'])

        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.qb_opening_snapshot_id, snapshot)
        self.assertEqual(sum(move.line_ids.mapped('debit')), 500.0)
        self.assertEqual(sum(move.line_ids.mapped('credit')), 500.0)

        with self.assertRaises(Exception):
            wizard.action_post_opening_balances()

    def test_migration_wizard_auto_posts_opening_move_in_live_mode(self):
        cash = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Wizard Opening Cash',
            'code': '1091',
            'account_type': 'asset_cash',
            'qb_account_id': '110',
        })
        revenue = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Wizard Opening Revenue',
            'code': '4091',
            'account_type': 'income',
            'qb_account_id': '120',
        })
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'TrialBalance',
            'period_start': '2026-02-01',
            'period_end': '2026-02-28',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 2,
        })
        for account, qb_id, amount in ((cash, '110', 250.0), (revenue, '120', -250.0)):
            self.env['quickbooks.account.balance'].create({
                'company_id': self.company.id,
                'account_id': account.id,
                'qb_account_id': qb_id,
                'account_name': account.name,
                'report_type': 'TrialBalance',
                'period_end': '2026-02-28',
                'balance': amount,
                'debit_balance': amount if amount > 0 else 0.0,
                'credit_balance': abs(amount) if amount < 0 else 0.0,
                'currency_id': self.company.currency_id.id,
                'snapshot_id': snapshot.id,
            })
        wizard = self.env['quickbooks.migration.wizard'].create({
            'company_id': self.company.id,
            'direction': 'import',
            'mode': 'live',
            'migrate_accounts': False,
            'migrate_opening_balances': True,
            'migrate_tax_codes': False,
            'migrate_customers': False,
            'migrate_vendors': False,
            'migrate_projects': False,
            'migrate_products': False,
            'migrate_invoices': False,
            'migrate_bills': False,
            'migrate_payments': False,
        })

        action = wizard.action_start_migration()
        move = self.env['account.move'].browse(action['res_id'])

        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.qb_opening_snapshot_id, snapshot)

    def test_opening_balances_refuse_unmatched_rows(self):
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'TrialBalance',
            'period_start': '2026-03-01',
            'period_end': '2026-03-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 1,
        })
        self.env['quickbooks.account.balance'].create({
            'company_id': self.company.id,
            'qb_account_id': '404',
            'account_name': 'Unmatched Opening Row',
            'report_type': 'TrialBalance',
            'period_end': '2026-03-31',
            'balance': 100.0,
            'debit_balance': 100.0,
            'currency_id': self.company.currency_id.id,
            'snapshot_id': snapshot.id,
        })
        journal = self.env['qb.sync.journals'].ensure_general_journal(
            self.config, key='qbo:general:opening',
            name='QuickBooks Opening Balances',
        )
        equity = self.env['qb.post.opening.balances.wizard']._opening_equity_account(
            self.company,
        )
        wizard = self.env['qb.post.opening.balances.wizard'].create({
            'company_id': self.company.id,
            'as_of_date': '2026-03-31',
            'snapshot_id': snapshot.id,
            'target_journal_id': journal.id,
            'opening_equity_account_id': equity.id,
            'retained_earnings_account_id': equity.id,
            'dry_run': False,
        })

        with self.assertRaises(Exception):
            wizard.action_post_opening_balances()
