"""Sales-document relinker tests.

Covers the four historical-migration scenarios called out in the plan:

  1. Quotation -> SO -> partial invoices: one Estimate, two Invoices,
     each carrying ``LinkedTxn[TxnType=Estimate]`` to that Estimate.
  2. Fully invoiced SO: Estimate + one Invoice that consumes the full
     amount.
  3. Estimate with no invoices yet: imported Estimate must remain on
     the SO without erroring out the relinker.
  4. CreditMemo linked back to Invoice via ``LinkedTxn[TxnType=Invoice]``
     -> Odoo ``reversed_entry_id`` populated.

These tests are skipped when the optional ``sale`` module is not
installed because the Estimate <-> Invoice chain only exists when the
``quickbooks_api_connector_sale`` bridge is loaded.
"""

import unittest

from .common import QuickbooksTestCommon


class TestSalesDocRelinker(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'sale.order' not in cls.env:
            raise unittest.SkipTest('sale module not installed')
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Relinker Customer',
            'customer_rank': 1,
            'qb_customer_id': '5500',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Relinker Product',
            'list_price': 100.0,
            'qb_item_id': '5300',
        })

    # ------------------------------------------------------------------
    # Helpers to fabricate QBO payloads
    # ------------------------------------------------------------------

    def _qb_estimate(self, qb_id, doc_number, lines):
        return {
            'Id': qb_id,
            'SyncToken': '0',
            'DocNumber': doc_number,
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-01-15',
            'TotalAmt': sum(l.get('Amount', 0) for l in lines),
            'Line': lines,
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

    def _qb_invoice(self, qb_id, doc_number, lines, linked_estimate_id=None):
        invoice = {
            'Id': qb_id,
            'SyncToken': '0',
            'DocNumber': doc_number,
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-01-20',
            'TotalAmt': sum(l.get('Amount', 0) for l in lines),
            'Line': lines,
            'MetaData': {'LastUpdatedTime': '2026-01-20T10:00:00Z'},
        }
        if linked_estimate_id:
            invoice['LinkedTxn'] = [{
                'TxnId': linked_estimate_id, 'TxnType': 'Estimate',
            }]
        return invoice

    def _qb_credit_memo(self, qb_id, doc_number, lines, linked_invoice_id=None):
        cm = {
            'Id': qb_id,
            'SyncToken': '0',
            'DocNumber': doc_number,
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-02-01',
            'TotalAmt': sum(l.get('Amount', 0) for l in lines),
            'Line': lines,
            'MetaData': {'LastUpdatedTime': '2026-02-01T10:00:00Z'},
        }
        if linked_invoice_id:
            cm['LinkedTxn'] = [{
                'TxnId': linked_invoice_id, 'TxnType': 'Invoice',
            }]
        return cm

    def _item_line(self, qb_line_id, qty, unit_price, description='Item'):
        amount = qty * unit_price
        return {
            'Id': str(qb_line_id),
            'DetailType': 'SalesItemLineDetail',
            'Amount': amount,
            'Description': description,
            'SalesItemLineDetail': {
                'Qty': qty,
                'UnitPrice': unit_price,
                'ItemRef': {'value': self.product.qb_item_id},
            },
        }

    # ------------------------------------------------------------------
    # 1. Quotation -> SO -> partial invoices
    # ------------------------------------------------------------------

    def test_partial_invoices_relink_to_single_estimate(self):
        est_lines = [
            self._item_line(qb_line_id=10, qty=5, unit_price=100, description='Widget'),
        ]
        inv1_lines = [
            self._item_line(qb_line_id=10, qty=2, unit_price=100, description='Widget'),
        ]
        inv2_lines = [
            self._item_line(qb_line_id=10, qty=3, unit_price=100, description='Widget'),
        ]

        self.env['qb.sync.estimates']._apply_pull(
            self._qb_estimate('1001', 'EST-001', est_lines), self.config,
        )
        invoices_service = self.env['qb.sync.invoices']
        meta = invoices_service._get_meta('invoice')
        invoices_service._apply_pull(
            self._qb_invoice('2001', 'INV-001', inv1_lines, linked_estimate_id='1001'),
            'invoice', meta, self.config,
        )
        invoices_service._apply_pull(
            self._qb_invoice('2002', 'INV-002', inv2_lines, linked_estimate_id='1001'),
            'invoice', meta, self.config,
        )

        # Both invoices must immediately point at the Odoo SO.
        sale_order = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1001')], limit=1,
        )
        self.assertTrue(sale_order, 'Estimate should have been imported as a sale.order')
        invoices = self.env['account.move'].search([
            ('qb_invoice_id', 'in', ('2001', '2002')),
        ], order='qb_invoice_id')
        self.assertEqual(len(invoices), 2)
        for inv in invoices:
            self.assertEqual(inv.qb_source_sale_order_id, sale_order)
            self.assertEqual(inv.invoice_origin, sale_order.name)
            # Per-line sale_line_ids must be populated via qb_line_id match.
            for line in inv.invoice_line_ids:
                if line.qb_line_id == '10':
                    so_line = sale_order.order_line.filtered(
                        lambda l: l.qb_line_id == '10',
                    )
                    self.assertTrue(so_line)
                    self.assertIn(so_line, line.sale_line_ids)

        # Relinker is idempotent — running it again must not duplicate links.
        counters = self.env['qb.sales.doc.relinker'].relink_all(self.config)
        self.assertEqual(counters['invoice']['imported'], 2)
        self.assertEqual(counters['invoice']['linked'], 2)
        self.assertEqual(counters['invoice']['orphan'], 0)

    # ------------------------------------------------------------------
    # 2. Fully invoiced SO
    # ------------------------------------------------------------------

    def test_fully_invoiced_estimate_links_full_amount(self):
        est_lines = [self._item_line(qb_line_id=20, qty=3, unit_price=200)]
        inv_lines = [self._item_line(qb_line_id=20, qty=3, unit_price=200)]
        self.env['qb.sync.estimates']._apply_pull(
            self._qb_estimate('1010', 'EST-010', est_lines), self.config,
        )
        invoices_service = self.env['qb.sync.invoices']
        meta = invoices_service._get_meta('invoice')
        invoices_service._apply_pull(
            self._qb_invoice('2010', 'INV-010', inv_lines, linked_estimate_id='1010'),
            'invoice', meta, self.config,
        )
        sale_order = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1010')], limit=1,
        )
        invoice = self.env['account.move'].search(
            [('qb_invoice_id', '=', '2010')], limit=1,
        )
        self.assertEqual(invoice.qb_source_sale_order_id, sale_order)
        self.assertEqual(invoice.amount_total, sale_order.amount_total)

    # ------------------------------------------------------------------
    # 3. Estimate with no invoices yet
    # ------------------------------------------------------------------

    def test_estimate_without_invoices_does_not_orphan(self):
        est_lines = [self._item_line(qb_line_id=30, qty=1, unit_price=50)]
        self.env['qb.sync.estimates']._apply_pull(
            self._qb_estimate('1020', 'EST-020', est_lines), self.config,
        )
        counters = self.env['qb.sales.doc.relinker'].relink_all(self.config)
        self.assertGreaterEqual(counters['estimate']['imported'], 1)
        # Invoice bucket should not flag the orphan (there is no invoice).
        # Find the specific SO and confirm it has no linked invoices.
        sale_order = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1020')], limit=1,
        )
        self.assertEqual(len(sale_order.qb_invoice_ids), 0)

    # ------------------------------------------------------------------
    # 4. CreditMemo linked back to Invoice
    # ------------------------------------------------------------------

    def test_credit_memo_links_to_source_invoice(self):
        # Import a standalone invoice (no estimate).
        invoice_payload = self._qb_invoice(
            '2030', 'INV-030',
            [self._item_line(qb_line_id=40, qty=1, unit_price=300)],
        )
        invoices_service = self.env['qb.sync.invoices']
        invoices_service._apply_pull(
            invoice_payload, 'invoice', invoices_service._get_meta('invoice'),
            self.config,
        )
        invoice = self.env['account.move'].search(
            [('qb_invoice_id', '=', '2030')], limit=1,
        )

        cm_payload = self._qb_credit_memo(
            '3030', 'CN-030',
            [self._item_line(qb_line_id=40, qty=1, unit_price=300)],
            linked_invoice_id='2030',
        )
        invoices_service._apply_pull(
            cm_payload, 'credit_memo', invoices_service._get_meta('credit_memo'),
            self.config,
        )
        credit_memo = self.env['account.move'].search(
            [('qb_creditmemo_id', '=', '3030')], limit=1,
        )
        self.assertEqual(credit_memo.move_type, 'out_refund')
        self.assertEqual(credit_memo.qb_source_invoice_qb_id, '2030')
        self.assertEqual(credit_memo.reversed_entry_id, invoice)

        # Relinker counters confirm the chain is fully resolved.
        counters = self.env['qb.sales.doc.relinker'].relink_all(self.config)
        self.assertEqual(counters['credit_memo']['orphan'], 0)
        self.assertGreaterEqual(counters['credit_memo']['linked'], 1)

    # ------------------------------------------------------------------
    # 5. Out-of-order: child imported before parent, second pass fixes it
    # ------------------------------------------------------------------

    def test_invoice_before_estimate_is_relinked_on_second_pass(self):
        # Import an invoice that references an estimate that does not
        # exist in Odoo yet.
        inv_lines = [self._item_line(qb_line_id=50, qty=4, unit_price=25)]
        invoice_payload = self._qb_invoice(
            '2040', 'INV-040', inv_lines, linked_estimate_id='1040',
        )
        invoices_service = self.env['qb.sync.invoices']
        invoices_service._apply_pull(
            invoice_payload, 'invoice', invoices_service._get_meta('invoice'),
            self.config,
        )
        invoice = self.env['account.move'].search(
            [('qb_invoice_id', '=', '2040')], limit=1,
        )
        # Parent SO is not imported yet — invoice carries the QBO id only.
        self.assertEqual(invoice.qb_source_estimate_qb_id, '1040')
        self.assertFalse(invoice.qb_source_sale_order_id)

        # Now import the parent estimate.
        est_lines = [self._item_line(qb_line_id=50, qty=4, unit_price=25)]
        self.env['qb.sync.estimates']._apply_pull(
            self._qb_estimate('1040', 'EST-040', est_lines), self.config,
        )

        # Second-pass relink rebuilds the link.
        counters = self.env['qb.sales.doc.relinker'].relink_all(self.config)
        invoice.invalidate_recordset()
        self.assertTrue(invoice.qb_source_sale_order_id)
        self.assertEqual(counters['invoice']['orphan'], 0)
