from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncPurchaseOrders(QuickbooksTestCommon):

    def test_pull_updates_existing_po(self):
        client = self._mock_client()
        partner = self.env['res.partner'].create({
            'name': 'Test Vendor',
            'supplier_rank': 1,
        })
        po = self.env['purchase.order'].create({
            'partner_id': partner.id,
            'qb_po_id': '1200',
        })

        qb_data = self._make_qb_purchase_order()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1200'
        job.odoo_record_id = po.id
        job.entity_type = 'purchase_order'
        job.direction = 'pull'

        service = self.env['qb.sync.purchase.orders']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1200')

        po.invalidate_recordset()
        self.assertTrue(po.qb_last_synced)
