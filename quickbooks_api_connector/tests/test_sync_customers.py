from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from .common import QuickbooksTestCommon


class TestSyncCustomers(QuickbooksTestCommon):

    def test_odoo_to_qb_customer_mapping(self):
        """Test Odoo partner → QBO Customer field mapping."""
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'John Doe',
            'email': 'john@example.com',
            'phone': '555-0001',
            'street': '100 Main St',
            'city': 'Springfield',
            'zip': '62701',
            'customer_rank': 1,
        })
        service = self.env['qb.sync.customers']
        data = service._odoo_to_qb_customer(partner)

        self.assertEqual(data['DisplayName'], 'John Doe')
        self.assertEqual(data['GivenName'], 'John')
        self.assertEqual(data['PrimaryEmailAddr']['Address'], 'john@example.com')
        self.assertEqual(data['PrimaryPhone']['FreeFormNumber'], '555-0001')
        self.assertEqual(data['BillAddr']['Line1'], '100 Main St')
        self.assertEqual(data['BillAddr']['City'], 'Springfield')

    def test_qb_customer_to_odoo_mapping(self):
        """Test QBO Customer → Odoo partner field mapping."""
        service = self.env['qb.sync.customers']
        qb_data = self._make_qb_customer()['Customer']
        vals = service._qb_customer_to_odoo(qb_data)

        self.assertEqual(vals['name'], 'Test Customer')
        self.assertEqual(vals['email'], 'test@example.com')
        self.assertEqual(vals['phone'], '555-1234')
        self.assertEqual(vals['street'], '123 Test St')
        self.assertEqual(vals['city'], 'Testville')
        self.assertEqual(vals['qb_customer_id'], '100')
        self.assertEqual(vals['customer_rank'], 1)

    def test_push_creates_new_customer(self):
        """Test pushing a new customer to QBO."""
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'New Customer',
            'email': 'new@example.com',
            'customer_rank': 1,
        })
        client = self._mock_client()
        client.create.return_value = {
            'Customer': {'Id': '999', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'customer'
        job.odoo_record_id = partner.id
        job.odoo_model = 'res.partner'
        job.qb_entity_id = False

        service = self.env['qb.sync.customers']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '999')
        client.create.assert_called_once()
        partner.invalidate_recordset()
        self.assertEqual(partner.qb_customer_id, '999')

    def test_push_updates_existing_customer(self):
        """Test updating an existing customer in QBO."""
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Existing Customer',
            'customer_rank': 1,
            'qb_customer_id': '888',
        })
        client = self._mock_client()
        client.read.return_value = {
            'Customer': {'Id': '888', 'SyncToken': '3'},
        }
        client.update.return_value = {
            'Customer': {'Id': '888', 'SyncToken': '4'},
        }

        job = MagicMock()
        job.entity_type = 'customer'
        job.odoo_record_id = partner.id
        job.odoo_model = 'res.partner'

        service = self.env['qb.sync.customers']
        result = service.push(client, self.config, job)

        client.update.assert_called_once()
        payload = client.update.call_args[0][1]
        self.assertEqual(payload['Id'], '888')
        self.assertEqual(payload['SyncToken'], '3')
        self.assertTrue(payload['sparse'])

    def test_pull_creates_new_partner(self):
        """Test pulling a customer creates a new partner in Odoo."""
        client = self._mock_client()
        client.read.return_value = self._make_qb_customer(qb_id='101')

        job = MagicMock()
        job.entity_type = 'customer'
        job.qb_entity_id = '101'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.customers']
        result = service.pull(client, self.config, job)

        self.assertEqual(result['qb_id'], '101')
        partner = self.env['res.partner'].search([
            ('qb_customer_id', '=', '101'),
        ], limit=1)
        self.assertTrue(partner)
        self.assertEqual(partner.name, 'Test Customer')

    def test_pull_updates_existing_partner(self):
        """Test pulling a customer updates an existing Odoo partner."""
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Old Name',
            'qb_customer_id': '102',
            'customer_rank': 1,
        })
        client = self._mock_client()
        client.read.return_value = self._make_qb_customer(
            qb_id='102', name='Updated Name',
        )

        job = MagicMock()
        job.entity_type = 'customer'
        job.qb_entity_id = '102'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.customers']
        service.pull(client, self.config, job)

        partner.invalidate_recordset()
        self.assertEqual(partner.name, 'Updated Name')

    def test_pull_links_existing_partner_by_email_without_duplicate(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Unlinked Customer',
            'email': 'test@example.com',
            'customer_rank': 1,
        })
        client = self._mock_client()
        client.read.return_value = self._make_qb_customer(qb_id='103')

        job = MagicMock()
        job.entity_type = 'customer'
        job.qb_entity_id = '103'
        job.odoo_record_id = None
        job.write = MagicMock()

        self.env['qb.sync.customers'].pull(client, self.config, job)

        partner.invalidate_recordset()
        self.assertEqual(partner.qb_customer_id, '103')
        self.assertEqual(
            self.env['res.partner'].search_count([('email', '=', 'test@example.com')]),
            1,
        )

    def test_vendor_mapping(self):
        """Test vendor-specific field mapping."""
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Vendor Corp',
            'email': 'vendor@corp.com',
            'vat': 'TAX123',
            'supplier_rank': 1,
        })
        service = self.env['qb.sync.customers']
        data = service._odoo_to_qb_vendor(partner)

        self.assertEqual(data['DisplayName'], 'Vendor Corp')
        self.assertEqual(data['TaxIdentifier'], 'TAX123')
