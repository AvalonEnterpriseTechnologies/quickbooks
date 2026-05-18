from .common import QuickbooksTestCommon


class TestSyncPaymentsBankJournal(QuickbooksTestCommon):
    """Bank journal resolution for QBO Payment / BillPayment payloads."""

    def setUp(self):
        super().setUp()
        Account = self.env['account.account']
        Journal = self.env['account.journal']

        self.bank_account_main = Account.with_context(skip_qb_sync=True).create({
            'name': '101401 Bank',
            'code': '101401',
            'account_type': 'asset_cash',
            'qb_account_id': '42',
            'qb_account_type': 'Bank',
            'qb_account_subtype': 'Checking',
            'qb_account_code': '101401',
        })
        self.bank_journal_main = Journal.create({
            'name': 'Bank',
            'type': 'bank',
            'code': 'BNK1',
            'company_id': self.company.id,
            'default_account_id': self.bank_account_main.id,
            'qb_account_id': '42',
        })

        self.bank_account_alt = Account.with_context(skip_qb_sync=True).create({
            'name': '101405 15008428',
            'code': '101405',
            'account_type': 'asset_cash',
            'qb_account_id': '55',
            'qb_account_type': 'Bank',
            'qb_account_subtype': 'Checking',
            'qb_account_code': '101405',
        })
        self.bank_journal_alt = Journal.create({
            'name': 'Mid America Business Platinum Checking',
            'type': 'bank',
            'code': 'BNK2',
            'company_id': self.company.id,
            'default_account_id': self.bank_account_alt.id,
        })

    def test_customer_payment_resolves_journal_from_deposit_account_ref(self):
        qb_data = {
            'Id': '600',
            'SyncToken': '0',
            'TotalAmt': 100.0,
            'TxnDate': '2026-01-15',
            'CustomerRef': {'value': 'NO_MATCH'},
            'DepositToAccountRef': {'value': '42'},
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

        vals = self.env['qb.sync.payments']._qb_payment_to_odoo(qb_data, self.config)

        self.assertEqual(vals.get('journal_id'), self.bank_journal_main.id,
                         'DepositToAccountRef must resolve to the pre-linked bank journal')
        self.assertFalse(vals.get('qb_sync_error'))

    def test_bill_payment_resolves_journal_from_check_bank_account_ref(self):
        qb_data = {
            'Id': '601',
            'SyncToken': '0',
            'TotalAmt': 75.0,
            'TxnDate': '2026-01-15',
            'VendorRef': {'value': 'NO_MATCH'},
            'CheckPayment': {'BankAccountRef': {'value': '55'}},
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

        vals = self.env['qb.sync.payments']._qb_billpayment_to_odoo(qb_data, self.config)

        self.assertEqual(vals.get('journal_id'), self.bank_journal_alt.id,
                         'BankAccountRef must resolve to the matching Odoo bank journal')
        self.assertFalse(vals.get('qb_sync_error'))

    def test_bill_payment_resolves_journal_from_credit_card_ref(self):
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        cc_account = Account.with_context(skip_qb_sync=True).create({
            'name': '201100 Credit Card',
            'code': '201100',
            'account_type': 'liability_credit_card',
            'qb_account_id': '88',
            'qb_account_type': 'Credit Card',
            'qb_account_code': '201100',
        })
        cc_journal = Journal.create({
            'name': 'Credit Card',
            'type': 'bank',
            'code': 'CC1',
            'company_id': self.company.id,
            'default_account_id': cc_account.id,
            'qb_account_id': '88',
        })
        qb_data = {
            'Id': '602',
            'SyncToken': '0',
            'TotalAmt': 25.0,
            'TxnDate': '2026-01-15',
            'VendorRef': {'value': 'NO_MATCH'},
            'CreditCardPayment': {'CCAccountRef': {'value': '88'}},
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

        vals = self.env['qb.sync.payments']._qb_billpayment_to_odoo(qb_data, self.config)

        self.assertEqual(vals.get('journal_id'), cc_journal.id)

    def test_unmapped_bank_ref_sets_qb_sync_error(self):
        qb_data = {
            'Id': '603',
            'SyncToken': '0',
            'TotalAmt': 100.0,
            'TxnDate': '2026-01-15',
            'CustomerRef': {'value': 'NO_MATCH'},
            'DepositToAccountRef': {'value': '999_UNKNOWN'},
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

        vals = self.env['qb.sync.payments']._qb_payment_to_odoo(qb_data, self.config)

        self.assertNotIn('journal_id', vals,
                         'Unmapped bank ref must not pin a wrong journal')
        self.assertIn('999_UNKNOWN', vals.get('qb_sync_error') or '',
                      'Unmapped bank ref must record an explanatory sync error')

    def test_payment_without_bank_ref_does_not_set_journal(self):
        qb_data = {
            'Id': '604',
            'SyncToken': '0',
            'TotalAmt': 100.0,
            'TxnDate': '2026-01-15',
            'CustomerRef': {'value': 'NO_MATCH'},
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

        vals = self.env['qb.sync.payments']._qb_payment_to_odoo(qb_data, self.config)

        self.assertNotIn('journal_id', vals)
        self.assertFalse(vals.get('qb_sync_error'))
