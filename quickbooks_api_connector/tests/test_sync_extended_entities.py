from unittest.mock import MagicMock, patch

from .common import QuickbooksTestCommon


class TestExtendedEntitySync(QuickbooksTestCommon):

    def test_open_or_setup_uses_sync_panel_when_configured(self):
        action = self.env['quickbooks.config'].action_open_or_setup()
        self.assertEqual(action['res_model'], 'res.config.settings')

    def test_sync_now_requires_connected_config(self):
        self.config.state = 'connected'
        with patch.object(
            self.env['qb.sync.engine'].__class__, 'run_full_sync',
            return_value=None,
        ) as run_full_sync:
            self.config.action_sync_now()
        run_full_sync.assert_called_once()

    def test_cdc_enqueue_path_uses_changed_records(self):
        client = self._mock_client()
        client.cdc.return_value = {
            'Customer': [{'Id': '100'}],
            'Invoice': [{'Id': '400'}],
        }
        engine = self.env['qb.sync.engine']
        self.config.last_sync_date = '2026-01-01 00:00:00'

        with patch.object(
            self.env['quickbooks.sync.queue'].__class__, 'enqueue',
            return_value=self.env['quickbooks.sync.queue'],
        ) as enqueue:
            records = engine._collect_cdc_records(
                client, self.config, ['customer', 'invoice'],
            )
            engine._enqueue_cdc_records(self.config, 'customer', records['customer'])

        self.assertIn('customer', records)
        enqueue.assert_called()

    def test_attachment_pull_creates_ir_attachment(self):
        client = self._mock_client()
        client.read.return_value = {
            'Attachable': {
                'Id': '900',
                'FileName': 'receipt.pdf',
                'ContentType': 'application/pdf',
                'FileAccessUri': 'https://example.test/receipt.pdf',
            },
        }
        job = self.env['quickbooks.sync.queue'].new({'qb_entity_id': '900'})
        service = self.env['qb.sync.attachments']

        with patch(
            'odoo.addons.quickbooks_api_connector.services.sync_attachments.http_requests'
        ) as mock_requests:
            mock_requests.get.return_value = MagicMock(
                status_code=200,
                content=b'pdf-bytes',
                headers={'content-type': 'application/pdf'},
            )
            service.pull(client, self.config, job)

        attachment = self.env['ir.attachment'].search([
            ('name', '=', 'receipt.pdf'),
        ], limit=1)
        self.assertTrue(attachment)

    def test_terms_push_payload(self):
        term = self.env['account.payment.term'].create({'name': 'Net 30'})
        client = self._mock_client()
        client.create.return_value = {'Term': {'Id': '12', 'SyncToken': '0'}}
        job = self.env['quickbooks.sync.queue'].new({
            'odoo_record_id': term.id,
        })

        self.env['qb.sync.terms'].push(client, self.config, job)

        self.assertEqual(term.qb_term_id, '12')
        client.create.assert_called_once()

    def test_payroll_compensations_are_persisted(self):
        data = {
            'payrollEmployeeCompensations': [{
                'employeeId': 'E1',
                'compensations': [{
                    'id': 'C1',
                    'name': 'Salary',
                    'type': 'salary',
                    'active': True,
                }],
            }],
        }
        count = self.env['qb.sync.payroll']._upsert_compensations(data, self.config)

        self.assertEqual(count, 1)
        comp = self.env['quickbooks.payroll.compensation'].search([
            ('qb_employee_id', '=', 'E1'),
            ('qb_compensation_id', '=', 'C1'),
        ], limit=1)
        self.assertEqual(comp.name, 'Salary')
