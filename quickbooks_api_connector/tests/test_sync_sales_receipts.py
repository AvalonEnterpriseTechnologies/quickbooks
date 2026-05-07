from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncSalesReceipts(QuickbooksTestCommon):

    def test_pull_updates_existing_move(self):
        client = self._mock_client()
        qb_data = self._make_qb_sales_receipt()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1100'
        job.odoo_record_id = None
        job.entity_type = 'sales_receipt'
        job.direction = 'pull'

        service = self.env['qb.sync.sales.receipts']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1100')
