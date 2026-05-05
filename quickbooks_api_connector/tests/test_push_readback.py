from unittest.mock import MagicMock, patch

from .common import QuickbooksTestCommon


class TestPushReadback(QuickbooksTestCommon):

    def test_push_readback_logs_warning_on_sync_token_drift(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Readback Customer',
            'customer_rank': 1,
            'qb_customer_id': '7001',
            'qb_sync_token': '1',
        })
        job = self.env['quickbooks.sync.queue'].create({
            'company_id': self.company.id,
            'entity_type': 'customer',
            'direction': 'push',
            'operation': 'update',
            'odoo_record_id': partner.id,
            'odoo_model': 'res.partner',
            'qb_entity_id': '7001',
        })
        client = self._mock_client()
        client.read.return_value = {
            'Customer': {
                'Id': '7001',
                'SyncToken': '2',
                'DisplayName': 'Readback Customer',
            },
        }

        self.env['qb.sync.engine']._verify_push_readback(
            client, self.config, job, {'qb_id': '7001'},
        )

        warning = self.env['quickbooks.sync.log'].search([
            ('qb_entity_id', '=', '7001'),
            ('state', '=', 'warning'),
        ], limit=1)
        self.assertTrue(warning)
        self.assertIn('SyncToken', warning.error_message)

    def test_execute_job_calls_readback_after_push(self):
        job = self.env['quickbooks.sync.queue'].create({
            'company_id': self.company.id,
            'entity_type': 'customer',
            'direction': 'push',
            'operation': 'update',
            'odoo_record_id': 1,
            'odoo_model': 'res.partner',
        })

        with patch.object(type(self.env['qb.sync.customers']), 'push', return_value={'qb_id': '8001'}), \
             patch.object(type(self.env['qb.sync.engine']), '_verify_push_readback') as verify:
            self.env['qb.sync.engine'].execute_job(job)

        verify.assert_called_once()
