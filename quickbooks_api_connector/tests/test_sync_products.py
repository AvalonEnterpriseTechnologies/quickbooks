from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncProducts(QuickbooksTestCommon):

    def test_odoo_to_qb_item_mapping(self):
        """Test Odoo product → QBO Item field mapping."""
        product = self.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Widget Pro',
            'default_code': 'WGT-PRO',
            'list_price': 49.99,
            'standard_price': 25.00,
            'type': 'consu',
        })
        service = self.env['qb.sync.products']
        data = service._odoo_to_qb_item(product)

        self.assertEqual(data['Name'], 'Widget Pro')
        self.assertEqual(data['Sku'], 'WGT-PRO')
        self.assertEqual(data['UnitPrice'], 49.99)
        self.assertEqual(data['PurchaseCost'], 25.00)
        self.assertEqual(data['Type'], 'NonInventory')

    def test_service_product_maps_to_service_type(self):
        product = self.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Consulting Hour',
            'type': 'service',
            'list_price': 150.00,
        })
        service = self.env['qb.sync.products']
        data = service._odoo_to_qb_item(product)
        self.assertEqual(data['Type'], 'Service')

    def test_qb_item_to_odoo_mapping(self):
        """Test QBO Item → Odoo product field mapping."""
        service = self.env['qb.sync.products']
        qb_data = self._make_qb_item()['Item']
        vals = service._qb_item_to_odoo(qb_data)

        self.assertEqual(vals['name'], 'Test Item')
        self.assertEqual(vals['default_code'], 'TEST-001')
        self.assertEqual(vals['list_price'], 99.99)
        self.assertEqual(vals['standard_price'], 50.00)
        self.assertEqual(vals['qb_item_id'], '300')

    def test_push_creates_new_item(self):
        product = self.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'New Product',
            'list_price': 29.99,
            'type': 'consu',
        })
        client = self._mock_client()
        client.create.return_value = {
            'Item': {'Id': '350', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'product'
        job.odoo_record_id = product.id
        job.odoo_model = 'product.product'

        service = self.env['qb.sync.products']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '350')
        product.invalidate_recordset()
        self.assertEqual(product.qb_item_id, '350')

    def test_pull_creates_new_product(self):
        client = self._mock_client()
        client.read.return_value = self._make_qb_item(qb_id='351')

        job = MagicMock()
        job.entity_type = 'product'
        job.qb_entity_id = '351'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.products']
        result = service.pull(client, self.config, job)

        product = self.env['product.product'].search([
            ('qb_item_id', '=', '351'),
        ], limit=1)
        self.assertTrue(product)
        self.assertEqual(product.name, 'Test Item')

    def test_pull_all_incremental(self):
        """Test incremental pull uses last_sync_date filter."""
        from datetime import datetime
        self.config.last_sync_date = datetime(2026, 1, 1, 0, 0, 0)

        client = self._mock_client()
        client.query_all.return_value = [
            self._make_qb_item(qb_id='360')['Item'],
        ]

        service = self.env['qb.sync.products']
        service.pull_all(client, self.config, 'product')

        call_args = client.query_all.call_args
        self.assertIn('MetaData.LastUpdatedTime', call_args[1].get('where_clause', ''))
