from .common import QuickbooksTestCommon


class TestSyncJournals(QuickbooksTestCommon):

    def test_bank_account_creates_idempotent_journal(self):
        account = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Operating Checking',
            'code': '1010',
            'account_type': 'asset_cash',
            'qb_account_id': '10',
            'qb_account_type': 'Bank',
            'qb_account_subtype': 'Checking',
            'qb_account_code': '1010',
        })
        service = self.env['qb.sync.journals']

        service.ensure_journals_for_accounts(self.config)
        service.ensure_journals_for_accounts(self.config)

        journals = self.env['account.journal'].search([
            ('qb_journal_key', '=', 'qbo:bank:10'),
        ])
        self.assertEqual(len(journals), 1)
        self.assertEqual(journals.default_account_id, account)

    def test_general_journal_is_created(self):
        journal = self.env['qb.sync.journals'].ensure_general_journal(
            self.config,
            key='qbo:general:default',
            name='QuickBooks Journal Entries',
        )

        self.assertEqual(journal.type, 'general')
        self.assertEqual(journal.qb_journal_key, 'qbo:general:default')
