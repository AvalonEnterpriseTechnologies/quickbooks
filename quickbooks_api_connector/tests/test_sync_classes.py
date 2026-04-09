from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncClasses(QuickbooksTestCommon):

    def test_pull_creates_analytic_account(self):
        client = self._mock_client()
        qb_data = self._make_qb_class()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1600'
        job.odoo_record_id = None
        job.entity_type = 'class'
        job.direction = 'pull'

        service = self.env['qb.sync.classes']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1600')
