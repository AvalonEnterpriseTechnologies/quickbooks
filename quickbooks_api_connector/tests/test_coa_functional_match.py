from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestCoAFunctionalMatch(QuickbooksTestCommon):

    def test_pull_all_links_existing_account_by_function_and_code(self):
        account = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Cash and Cash Equivalents',
            'code': '1010',
            'account_type': 'asset_cash',
        })
        client = self._mock_client()
        client.query_all.return_value = [{
            'Id': '10',
            'SyncToken': '0',
            'Name': 'Checking',
            'AcctNum': '1010',
            'AccountType': 'Bank',
            'AccountSubType': 'Checking',
            'CurrentBalance': 125.0,
        }]

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        account.invalidate_recordset()
        self.assertEqual(account.qb_account_id, '10')
        self.assertEqual(account.name, 'Cash and Cash Equivalents')
        self.assertEqual(account.qb_account_type, 'Bank')
        self.assertEqual(account.qb_account_subtype, 'Checking')
        self.assertFalse(self.env['account.account'].search([
            ('qb_account_id', '=', '10'),
            ('id', '!=', account.id),
        ]))

    def test_pull_all_creates_missing_qbo_account(self):
        client = self._mock_client()
        client.query_all.return_value = [{
            'Id': '20',
            'SyncToken': '0',
            'Name': 'Bank Service Charges',
            'AcctNum': '6050',
            'AccountType': 'Expense',
            'AccountSubType': 'BankCharges',
        }]

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        created = self.env['account.account'].search([
            ('qb_account_id', '=', '20'),
        ], limit=1)
        self.assertTrue(created)
        self.assertEqual(created.account_type, 'expense')

    def test_pull_all_includes_inactive_account_and_sets_company_ids(self):
        client = self._mock_client()
        client.query_all.return_value = [{
            'Id': '21',
            'SyncToken': '0',
            'Name': 'Old Bank Account',
            'AcctNum': '1060',
            'AccountType': 'Bank',
            'AccountSubType': 'Checking',
            'Active': False,
        }]

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        client.query_all.assert_called_once()
        where = client.query_all.call_args.kwargs.get('where_clause')
        self.assertIn('Active IN (true, false)', where)
        created = self.env['account.account'].search([
            ('qb_account_id', '=', '21'),
        ], limit=1)
        self.assertTrue(created)
        self.assertFalse(created.active)
        if 'company_ids' in created._fields:
            self.assertIn(self.company, created.company_ids)

    def test_pull_all_does_not_filter_by_last_sync_date(self):
        self.config.last_sync_date = '2026-01-31 12:00:00'
        client = self._mock_client()
        client.query_all.return_value = []

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        where = client.query_all.call_args.kwargs.get('where_clause')
        self.assertEqual(where, 'Active IN (true, false)')
        self.assertNotIn('MetaData.LastUpdatedTime', where)

    def test_single_pull_uses_new_matcher(self):
        account = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Accounts Payable',
            'code': '2000',
            'account_type': 'liability_payable',
        })
        client = self._mock_client()
        client.read.return_value = {'Account': {
            'Id': '30',
            'SyncToken': '0',
            'Name': 'A/P',
            'AcctNum': '2000',
            'AccountType': 'Accounts Payable',
            'AccountSubType': 'AccountsPayable',
        }}
        job = MagicMock(qb_entity_id='30')

        self.env['qb.sync.accounts'].pull(client, self.config, job)

        account.invalidate_recordset()
        self.assertEqual(account.qb_account_id, '30')
