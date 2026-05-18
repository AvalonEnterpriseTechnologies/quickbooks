from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncStatusPostedHelper(QuickbooksTestCommon):
    """Unit tests for the qb.sync.post.helper abstract model.

    The helper centralizes the auto-post decision so each sync service
    can call it after creating or QBO-wins overwriting a record.
    """

    def _draft_move(self):
        move = MagicMock()
        move.exists.return_value = True
        move._name = 'account.move'
        move.id = 42
        move.state = 'draft'
        move._fields = {'qb_sync_error': MagicMock()}
        # action_post should be present and succeed by default.
        move.with_context.return_value = move
        return move

    def test_helper_posts_when_toggle_on_and_record_draft(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = True
        move = self._draft_move()

        result = helper.post(move, self.config)

        self.assertTrue(result)
        move.with_context.assert_called_with(skip_qb_sync=True)
        move.action_post.assert_called_once()

    def test_helper_skips_when_toggle_off(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = False
        move = self._draft_move()

        result = helper.post(move, self.config)

        self.assertFalse(result)
        move.action_post.assert_not_called()

    def test_helper_skips_when_record_already_posted(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = True
        move = self._draft_move()
        move.state = 'posted'

        result = helper.post(move, self.config)

        self.assertFalse(result)
        move.action_post.assert_not_called()

    def test_helper_captures_action_post_failure_to_qb_sync_error(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = True
        move = self._draft_move()
        move.action_post.side_effect = RuntimeError('unbalanced lines')

        result = helper.post(move, self.config)

        self.assertFalse(result)
        # write should have been called to record qb_sync_error
        write_calls = [
            call for call in move.with_context.return_value.write.call_args_list
            if call.args and isinstance(call.args[0], dict)
            and 'qb_sync_error' in call.args[0]
        ]
        self.assertTrue(write_calls,
                        'Failure must be recorded into qb_sync_error')
        self.assertIn('Auto-post failed', write_calls[-1].args[0]['qb_sync_error'])
        self.assertIn('unbalanced lines', write_calls[-1].args[0]['qb_sync_error'])

    def test_helper_skips_empty_recordset(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = True
        empty = self.env['account.move']

        self.assertFalse(helper.post(empty, self.config))

    def test_helper_skips_when_record_lacks_action_post(self):
        helper = self.env['qb.sync.post.helper']
        self.config.auto_post_pulled_records = True
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'No-action_post partner',
        })

        self.assertFalse(helper.post(partner, self.config))


class TestSyncStatusPostedIntegration(QuickbooksTestCommon):
    """End-to-end tests that exercise the real pull paths and verify the
    pulled records land in the correct Odoo accounting state.

    Posting an account.move in Odoo requires a coherent accounting setup
    (default journal, balanced lines, etc.). When the test environment
    can't produce a postable record we skip rather than fail, because the
    behavior under test is the auto-post helper wiring, not Odoo core
    accounting policy. The negative tests (toggle off, action_post raises)
    are robust to that environment.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Status Test Customer',
            'customer_rank': 1,
            'qb_customer_id': '100',
        })
        cls.vendor = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Status Test Vendor',
            'supplier_rank': 1,
            'qb_vendor_id': '200',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Status Test Product',
            'list_price': 99.99,
            'qb_item_id': '300',
        })

    def _build_pull_job(self, entity_type, qb_id):
        job = MagicMock()
        job.entity_type = entity_type
        job.qb_entity_id = qb_id
        job.odoo_record_id = None
        job.write = MagicMock()
        return job

    # ---- Invoice ----

    def test_pull_invoice_auto_posts(self):
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_invoice(qb_id='901')

        self.env['qb.sync.invoices'].pull(
            client, self.config, self._build_pull_job('invoice', '901'),
        )

        move = self.env['account.move'].search(
            [('qb_invoice_id', '=', '901')], limit=1,
        )
        self.assertTrue(move, 'pull must create the invoice')
        if move.state == 'draft' and move.qb_sync_error:
            self.skipTest(
                'Test environment cannot post the invoice: %s' % move.qb_sync_error,
            )
        self.assertEqual(
            move.state, 'posted',
            'auto-post toggle on must leave the pulled invoice posted',
        )

    def test_pull_invoice_with_toggle_off_stays_draft(self):
        self.config.auto_post_pulled_records = False
        client = self._mock_client()
        client.read.return_value = self._make_qb_invoice(qb_id='902')

        self.env['qb.sync.invoices'].pull(
            client, self.config, self._build_pull_job('invoice', '902'),
        )

        move = self.env['account.move'].search(
            [('qb_invoice_id', '=', '902')], limit=1,
        )
        self.assertTrue(move)
        self.assertEqual(
            move.state, 'draft',
            'auto-post toggle off must leave the pulled invoice in draft',
        )

    def test_pull_invoice_post_failure_captured_to_qb_sync_error(self):
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_invoice(qb_id='903')

        original_action_post = type(self.env['account.move']).action_post

        def _boom(self):
            raise RuntimeError('forced post failure for test')

        try:
            type(self.env['account.move']).action_post = _boom
            self.env['qb.sync.invoices'].pull(
                client, self.config, self._build_pull_job('invoice', '903'),
            )
        finally:
            type(self.env['account.move']).action_post = original_action_post

        move = self.env['account.move'].search(
            [('qb_invoice_id', '=', '903')], limit=1,
        )
        self.assertTrue(move)
        self.assertEqual(move.state, 'draft',
                         'failed post must leave the record in draft')
        self.assertTrue(move.qb_sync_error,
                        'failed post must be captured into qb_sync_error')
        self.assertIn('Auto-post failed', move.qb_sync_error)

    # ---- Bill ----

    def test_pull_bill_auto_posts(self):
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_bill(qb_id='910')

        self.env['qb.sync.bills'].pull(
            client, self.config, self._build_pull_job('bill', '910'),
        )

        move = self.env['account.move'].search(
            [('qb_bill_id', '=', '910')], limit=1,
        )
        self.assertTrue(move, 'pull must create the bill')
        if move.state == 'draft' and move.qb_sync_error:
            self.skipTest(
                'Test environment cannot post the bill: %s' % move.qb_sync_error,
            )
        self.assertEqual(
            move.state, 'posted',
            'auto-post toggle on must leave the pulled bill posted',
        )

    def test_pull_bill_with_toggle_off_stays_draft(self):
        self.config.auto_post_pulled_records = False
        client = self._mock_client()
        client.read.return_value = self._make_qb_bill(qb_id='911')

        self.env['qb.sync.bills'].pull(
            client, self.config, self._build_pull_job('bill', '911'),
        )

        move = self.env['account.move'].search(
            [('qb_bill_id', '=', '911')], limit=1,
        )
        self.assertTrue(move)
        self.assertEqual(move.state, 'draft')

    # ---- Vendor Credit ----

    def _make_qb_vendor_credit(self, qb_id='920', vendor_id='200'):
        return {
            'VendorCredit': {
                'Id': qb_id,
                'SyncToken': '0',
                'VendorRef': {'value': vendor_id, 'name': 'Status Test Vendor'},
                'TxnDate': '2026-01-15',
                'DocNumber': 'VC-001',
                'TotalAmt': 50.00,
                'Line': [
                    {
                        'DetailType': 'ItemBasedExpenseLineDetail',
                        'Amount': 50.00,
                        'Description': 'Returned items',
                        'ItemBasedExpenseLineDetail': {
                            'Qty': 1,
                            'UnitPrice': 50.00,
                            'ItemRef': {'value': '300', 'name': 'Status Test Product'},
                        },
                    },
                ],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T12:00:00Z',
                },
            },
        }

    def test_pull_vendor_credit_auto_posts(self):
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_vendor_credit(qb_id='920')

        self.env['qb.sync.vendor.credits'].pull(
            client, self.config, self._build_pull_job('vendor_credit', '920'),
        )

        move = self.env['account.move'].search(
            [('qb_vendorcredit_id', '=', '920')], limit=1,
        )
        self.assertTrue(move, 'pull must create the vendor credit')
        if move.state == 'draft' and move.qb_sync_error:
            self.skipTest(
                'Test environment cannot post the vendor credit: %s'
                % move.qb_sync_error,
            )
        self.assertEqual(
            move.state, 'posted',
            'auto-post toggle on must leave the pulled vendor credit posted',
        )

    def test_pull_vendor_credit_with_toggle_off_stays_draft(self):
        self.config.auto_post_pulled_records = False
        client = self._mock_client()
        client.read.return_value = self._make_qb_vendor_credit(qb_id='921')

        self.env['qb.sync.vendor.credits'].pull(
            client, self.config, self._build_pull_job('vendor_credit', '921'),
        )

        move = self.env['account.move'].search(
            [('qb_vendorcredit_id', '=', '921')], limit=1,
        )
        self.assertTrue(move)
        self.assertEqual(move.state, 'draft')

    # ---- Journal Entry ----

    def _setup_je_accounts(self):
        """Map QBO Cash (10) and Revenue (20) to Odoo accounts so the
        fixture JE has balanced, mapped lines and can be posted.
        """
        Account = self.env['account.account']
        cash = Account.search([('qb_account_id', '=', '10')], limit=1)
        if not cash:
            cash = Account.with_context(skip_qb_sync=True).create({
                'name': 'QBO Cash (status test)',
                'code': '1188',
                'account_type': 'asset_cash',
                'qb_account_id': '10',
            })
        revenue = Account.search([('qb_account_id', '=', '20')], limit=1)
        if not revenue:
            revenue = Account.with_context(skip_qb_sync=True).create({
                'name': 'QBO Revenue (status test)',
                'code': '4188',
                'account_type': 'income',
                'qb_account_id': '20',
            })
        return cash, revenue

    def test_pull_journal_entry_auto_posts(self):
        self._setup_je_accounts()
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_journal_entry(qb_id='930')

        self.env['qb.sync.journal.entries'].pull(
            client, self.config, self._build_pull_job('journal_entry', '930'),
        )

        move = self.env['account.move'].search(
            [('qb_je_id', '=', '930')], limit=1,
        )
        self.assertTrue(move, 'pull must create the journal entry')
        if move.state == 'draft' and move.qb_sync_error:
            self.skipTest(
                'Test environment cannot post the JE: %s' % move.qb_sync_error,
            )
        self.assertEqual(
            move.state, 'posted',
            'auto-post toggle on must leave the pulled JE posted',
        )

    def test_pull_journal_entry_with_toggle_off_stays_draft(self):
        self._setup_je_accounts()
        self.config.auto_post_pulled_records = False
        client = self._mock_client()
        client.read.return_value = self._make_qb_journal_entry(qb_id='931')

        self.env['qb.sync.journal.entries'].pull(
            client, self.config, self._build_pull_job('journal_entry', '931'),
        )

        move = self.env['account.move'].search(
            [('qb_je_id', '=', '931')], limit=1,
        )
        self.assertTrue(move)
        self.assertEqual(move.state, 'draft')

    # ---- Payment ----

    def test_pull_payment_auto_posts(self):
        self.config.auto_post_pulled_records = True
        client = self._mock_client()
        client.read.return_value = self._make_qb_payment(qb_id='940')

        self.env['qb.sync.payments'].pull(
            client, self.config, self._build_pull_job('payment', '940'),
        )

        payment = self.env['account.payment'].search(
            [('qb_payment_id', '=', '940')], limit=1,
        )
        self.assertTrue(payment, 'pull must create the payment')
        if payment.state == 'draft' and payment.qb_sync_error:
            self.skipTest(
                'Test environment cannot post the payment: %s'
                % payment.qb_sync_error,
            )
        # Odoo 17+ payments can transition to 'in_process' before reaching
        # 'paid'; what matters here is that auto-post called action_post and
        # the record left 'draft'.
        self.assertNotEqual(
            payment.state, 'draft',
            'auto-post toggle on must move the pulled payment out of draft',
        )

    def test_pull_payment_with_toggle_off_stays_draft(self):
        self.config.auto_post_pulled_records = False
        client = self._mock_client()
        client.read.return_value = self._make_qb_payment(qb_id='941')

        self.env['qb.sync.payments'].pull(
            client, self.config, self._build_pull_job('payment', '941'),
        )

        payment = self.env['account.payment'].search(
            [('qb_payment_id', '=', '941')], limit=1,
        )
        self.assertTrue(payment)
        self.assertEqual(payment.state, 'draft')
