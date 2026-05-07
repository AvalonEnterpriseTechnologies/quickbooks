from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncBills(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Bill Vendor',
            'supplier_rank': 1,
            'qb_vendor_id': '200',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Bill Product',
            'standard_price': 50.00,
            'qb_item_id': '300',
        })

    def test_odoo_bill_to_qb_mapping(self):
        """Test Odoo vendor bill → QBO Bill mapping with item-based lines."""
        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_date': '2026-01-15',
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Purchased items',
                'quantity': 10,
                'price_unit': 50.00,
            })],
        })
        service = self.env['qb.sync.bills']
        data = service._odoo_bill_to_qb(move)

        self.assertEqual(data['VendorRef']['value'], '200')
        self.assertTrue(len(data['Line']) >= 1)
        line = data['Line'][0]
        self.assertEqual(line['DetailType'], 'ItemBasedExpenseLineDetail')

    def test_qb_bill_to_odoo_mapping(self):
        """Test QBO Bill → Odoo vendor bill mapping."""
        service = self.env['qb.sync.bills']
        qb_data = self._make_qb_bill()['Bill']
        vals = service._qb_bill_to_odoo(qb_data, self.config)

        self.assertEqual(vals['move_type'], 'in_invoice')
        self.assertEqual(vals['qb_bill_id'], '500')
        self.assertEqual(vals['partner_id'], self.vendor.id)

    def test_push_creates_new_bill(self):
        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Test',
                'quantity': 1,
                'price_unit': 100.00,
            })],
        })
        client = self._mock_client()
        client.create.return_value = {
            'Bill': {'Id': '550', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'bill'
        job.odoo_record_id = move.id
        job.odoo_model = 'account.move'

        service = self.env['qb.sync.bills']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '550')

    def test_pull_creates_new_bill(self):
        client = self._mock_client()
        client.read.return_value = self._make_qb_bill(qb_id='551')

        job = MagicMock()
        job.entity_type = 'bill'
        job.qb_entity_id = '551'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.bills']
        result = service.pull(client, self.config, job)

        move = self.env['account.move'].search([
            ('qb_bill_id', '=', '551'),
        ], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.move_type, 'in_invoice')
