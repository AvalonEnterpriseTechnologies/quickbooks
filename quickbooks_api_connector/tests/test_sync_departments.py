from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncDepartments(QuickbooksTestCommon):

    def test_pull_creates_department(self):
        client = self._mock_client()
        qb_data = self._make_qb_department()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '900'
        job.odoo_record_id = None
        job.entity_type = 'department'
        job.direction = 'pull'

        service = self.env['qb.sync.departments']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '900')

        dept = self.env['hr.department'].search([('qb_department_id', '=', '900')])
        self.assertTrue(dept)
        self.assertEqual(dept.name, 'Engineering')
