from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncTimeActivities(QuickbooksTestCommon):

    def test_pull_creates_timesheet_line(self):
        client = self._mock_client()
        qb_data = self._make_qb_time_activity()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1000'
        job.odoo_record_id = None
        job.entity_type = 'time_activity'
        job.direction = 'pull'

        service = self.env['qb.sync.time.activities']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1000')

        line = self.env['account.analytic.line'].search(
            [('qb_timeactivity_id', '=', '1000')]
        )
        self.assertTrue(line)
        self.assertAlmostEqual(line.unit_amount, 2.5, places=1)
