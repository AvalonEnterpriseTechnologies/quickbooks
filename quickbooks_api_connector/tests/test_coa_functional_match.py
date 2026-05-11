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
