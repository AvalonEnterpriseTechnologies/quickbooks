from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncTransfers(QuickbooksTestCommon):

    def test_pull_returns_id(self):
        client = self._mock_client()
        qb_data = self._make_qb_transfer()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1400'
        job.odoo_record_id = None
        job.entity_type = 'transfer'
        job.direction = 'pull'

        service = self.env['qb.sync.transfers']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1400')
