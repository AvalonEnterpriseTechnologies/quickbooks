"""CreditMemo pull-side coverage.

Verifies that ``qb.sync.invoices`` correctly handles ``credit_memo``
routing (move_type=out_refund + qb_creditmemo_id) and that a
``LinkedTxn[TxnType=Invoice]`` on the CreditMemo populates Odoo's
``account.move.reversed_entry_id`` once the parent Invoice exists.
"""

from .common import QuickbooksTestCommon


class TestSyncCreditMemos(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'CN Customer',
            'customer_rank': 1,
            'qb_customer_id': '7500',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'CN Product',
            'list_price': 80.0,
            'qb_item_id': '7300',
        })

    def _make_cm(self, qb_id, doc_number, linked_invoice_id=None):
        payload = {
            'Id': qb_id,
            'SyncToken': '0',
            'DocNumber': doc_number,
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-02-01',
            'TotalAmt': 80.0,
            'Line': [{
                'Id': '1',
                'DetailType': 'SalesItemLineDetail',
                'Amount': 80.0,
                'Description': 'Refunded item',
                'SalesItemLineDetail': {
                    'Qty': 1, 'UnitPrice': 80.0,
                    'ItemRef': {'value': self.product.qb_item_id},
                },
            }],
            'MetaData': {'LastUpdatedTime': '2026-02-01T10:00:00Z'},
        }
        if linked_invoice_id:
            payload['LinkedTxn'] = [{
                'TxnId': linked_invoice_id, 'TxnType': 'Invoice',
            }]
        return payload

    def test_credit_memo_creates_out_refund_move(self):
        service = self.env['qb.sync.invoices']
        meta = service._get_meta('credit_memo')
        service._apply_pull(self._make_cm('4001', 'CN-4001'), 'credit_memo', meta, self.config)
        cm = self.env['account.move'].search(
            [('qb_creditmemo_id', '=', '4001')], limit=1,
        )
        self.assertTrue(cm)
        self.assertEqual(cm.move_type, 'out_refund')
        self.assertEqual(cm.partner_id, self.customer)

    def test_linked_invoice_resolves_to_reversed_entry(self):
        invoices_service = self.env['qb.sync.invoices']
        # Import the parent invoice first.
        inv_payload = {
            'Id': '4099',
            'SyncToken': '0',
            'DocNumber': 'INV-4099',
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-01-15',
            'TotalAmt': 80.0,
            'Line': [{
                'Id': '1',
                'DetailType': 'SalesItemLineDetail',
                'Amount': 80.0,
                'Description': 'Original line',
                'SalesItemLineDetail': {
                    'Qty': 1, 'UnitPrice': 80.0,
                    'ItemRef': {'value': self.product.qb_item_id},
                },
            }],
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }
        invoices_service._apply_pull(
            inv_payload, 'invoice',
            invoices_service._get_meta('invoice'), self.config,
        )
        invoice = self.env['account.move'].search(
            [('qb_invoice_id', '=', '4099')], limit=1,
        )
        # Now the CreditMemo with LinkedTxn to that invoice.
        invoices_service._apply_pull(
            self._make_cm('4100', 'CN-4100', linked_invoice_id='4099'),
            'credit_memo', invoices_service._get_meta('credit_memo'),
            self.config,
        )
        cm = self.env['account.move'].search(
            [('qb_creditmemo_id', '=', '4100')], limit=1,
        )
        self.assertEqual(cm.qb_source_invoice_qb_id, '4099')
        self.assertEqual(cm.reversed_entry_id, invoice)
