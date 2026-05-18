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

    def test_adopts_existing_journal_pre_linked_by_qb_account_id(self):
        """Pre-linked operator journals must be adopted, not duplicated.

        Models the keep-existing-Odoo-CoA migration path: the operator
        sets account.journal.qb_account_id on BNK1 ('101401') before
        the connector ever runs, then the QBO account pull arrives. The
        connector must reuse BNK1 rather than create a parallel
        QBO-derived bank journal.
        """
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        odoo_account = Account.with_context(skip_qb_sync=True).create({
            'name': '101401 Bank',
            'code': '101401',
            'account_type': 'asset_cash',
            'qb_account_id': '42',
            'qb_account_type': 'Bank',
            'qb_account_subtype': 'Checking',
            'qb_account_code': '101401',
        })
        pre_linked = Journal.create({
            'name': 'Bank',
            'type': 'bank',
            'code': 'BNK1',
            'company_id': self.company.id,
            'default_account_id': odoo_account.id,
            'qb_account_id': '42',
        })

        self.env['qb.sync.journals'].ensure_journals_for_accounts(self.config)

        all_journals = Journal.search([
            ('company_id', '=', self.company.id),
            ('qb_account_id', '=', '42'),
        ])
        self.assertEqual(len(all_journals), 1,
                         'Pre-linked journal must be adopted; no duplicate created')
        adopted = all_journals
        self.assertEqual(adopted.id, pre_linked.id)
        self.assertEqual(adopted.qb_journal_key, 'qbo:bank:42',
                         'Adopted journal must receive the connector key for idempotency')
        self.assertEqual(adopted.default_account_id, odoo_account)

    def test_adopts_existing_journal_by_default_account(self):
        """Fallback: journal already pointing at the linked account is adopted."""
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        odoo_account = Account.with_context(skip_qb_sync=True).create({
            'name': '101405 15008428',
            'code': '101405',
            'account_type': 'asset_cash',
            'qb_account_id': '55',
            'qb_account_type': 'Bank',
            'qb_account_subtype': 'Checking',
            'qb_account_code': '101405',
        })
        existing = Journal.create({
            'name': 'Mid America Business Platinum Checking',
            'type': 'bank',
            'code': 'BNK2',
            'company_id': self.company.id,
            'default_account_id': odoo_account.id,
        })

        self.env['qb.sync.journals'].ensure_journals_for_accounts(self.config)

        adopted = Journal.search([
            ('company_id', '=', self.company.id),
            ('default_account_id', '=', odoo_account.id),
        ])
        self.assertEqual(len(adopted), 1, 'No duplicate journal must be created')
        self.assertEqual(adopted.id, existing.id)
        self.assertEqual(adopted.qb_account_id, '55')
        self.assertEqual(adopted.qb_journal_key, 'qbo:bank:55')
