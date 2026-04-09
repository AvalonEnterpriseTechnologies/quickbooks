from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncInvoices(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Invoice Customer',
            'customer_rank': 1,
            'qb_customer_id': '100',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Invoice Product',
            'list_price': 99.99,
            'qb_item_id': '300',
        })

    def test_odoo_invoice_to_qb_mapping(self):
        """Test invoice field and line item mapping."""
        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_date': '2026-01-15',
            'invoice_date_due': '2026-02-15',
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Test line',
                'quantity': 2,
                'price_unit': 99.99,
            })],
        })
        service = self.env['qb.sync.invoices']
        meta = service._get_meta('invoice')
        data = service._odoo_invoice_to_qb(move, meta)

        self.assertEqual(data['CustomerRef']['value'], '100')
        self.assertEqual(data['TxnDate'], '2026-01-15')
        self.assertTrue(len(data['Line']) >= 1)
        line = data['Line'][0]
        self.assertEqual(line['DetailType'], 'SalesItemLineDetail')
        self.assertEqual(line['SalesItemLineDetail']['Qty'], 2)

    def test_qb_invoice_to_odoo_mapping(self):
        """Test QBO Invoice → Odoo account.move mapping."""
        service = self.env['qb.sync.invoices']
        meta = service._get_meta('invoice')
        qb_data = self._make_qb_invoice()['Invoice']
        vals = service._qb_invoice_to_odoo(qb_data, meta, self.config)

        self.assertEqual(vals['move_type'], 'out_invoice')
        self.assertEqual(vals['qb_invoice_id'], '400')
        self.assertEqual(vals['partner_id'], self.customer.id)
        self.assertTrue(vals.get('invoice_line_ids'))

    def test_push_creates_new_invoice(self):
        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Test line',
                'quantity': 1,
                'price_unit': 99.99,
            })],
        })
        client = self._mock_client()
        client.create.return_value = {
            'Invoice': {'Id': '450', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'invoice'
        job.odoo_record_id = move.id
        job.odoo_model = 'account.move'

        service = self.env['qb.sync.invoices']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '450')
        move.invalidate_recordset()
        self.assertEqual(move.qb_invoice_id, '450')

    def test_pull_creates_new_invoice(self):
        client = self._mock_client()
        client.read.return_value = self._make_qb_invoice(qb_id='451')

        job = MagicMock()
        job.entity_type = 'invoice'
        job.qb_entity_id = '451'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.invoices']
        result = service.pull(client, self.config, job)

        move = self.env['account.move'].search([
            ('qb_invoice_id', '=', '451'),
        ], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.move_type, 'out_invoice')

    def test_credit_memo_mapping(self):
        """Test credit memo uses correct meta."""
        service = self.env['qb.sync.invoices']
        meta = service._get_meta('credit_memo')
        self.assertEqual(meta['qb_name'], 'CreditMemo')
        self.assertEqual(meta['move_type'], 'out_refund')
