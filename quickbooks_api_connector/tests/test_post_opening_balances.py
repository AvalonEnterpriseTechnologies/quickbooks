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
