from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncEmployees(QuickbooksTestCommon):

    def test_pull_creates_employee(self):
        client = self._mock_client()
        qb_data = self._make_qb_employee()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '800'
        job.odoo_record_id = None
        job.entity_type = 'employee'
        job.direction = 'pull'

        service = self.env['qb.sync.employees']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '800')

        emp = self.env['hr.employee'].search([('qb_employee_id', '=', '800')])
        self.assertTrue(emp)
        self.assertIn('John', emp.name)

    def test_pull_all_updates_existing(self):
        client = self._mock_client()
        emp = self.env['hr.employee'].create({
            'name': 'Old Name',
            'qb_employee_id': '800',
        })

        qb_list = [self._make_qb_employee()['Employee']]
        client.query_all.return_value = qb_list

        service = self.env['qb.sync.employees']
        service.pull_all(client, self.config, 'employee')

        emp.invalidate_recordset()
        self.assertEqual(emp.name, 'John Doe')
