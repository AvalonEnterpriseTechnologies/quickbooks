from unittest import SkipTest
from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncProjects(QuickbooksTestCommon):

    def setUp(self):
        super().setUp()
        if 'project.project' not in self.env:
            raise SkipTest('project module is not installed')

    def test_pull_project_creates_project(self):
        client = self._mock_client()
        client.read.return_value = {
            'Customer': {
                'Id': 'P1',
                'SyncToken': '0',
                'DisplayName': 'Website Launch',
                'IsProject': True,
                'ParentRef': {'value': '100'},
            },
        }
        client.get.return_value = {'Project': {'Id': 'P1'}}
        job = MagicMock(qb_entity_id='P1')

        result = self.env['qb.sync.projects'].pull(client, self.config, job)

        self.assertEqual(result['qb_id'], 'P1')
        project = self.env['project.project'].search([('qb_project_id', '=', 'P1')])
        self.assertEqual(project.name, 'Website Launch')

    def test_push_project_creates_qbo_project_customer(self):
        project = self.env['project.project'].create({'name': 'Mobile App'})
        client = self._mock_client()
        client.create.return_value = {'Customer': {'Id': 'P2', 'SyncToken': '1'}}
        client.post.return_value = {'Project': {'Id': 'P2'}}
        job = MagicMock(odoo_record_id=project.id)

        result = self.env['qb.sync.projects'].push(client, self.config, job)

        self.assertEqual(result['qb_id'], 'P2')
        self.assertEqual(project.qb_project_id, 'P2')
        client.create.assert_called_once()
        client.post.assert_called_once()
