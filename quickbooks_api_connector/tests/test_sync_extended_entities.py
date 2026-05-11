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

    def test_full_entity_queue_job_dispatches_pull_all(self):
        client = self._mock_client()
        job = self.env['quickbooks.sync.queue'].new({
            'company_id': self.company.id,
            'entity_type': 'customer',
            'direction': 'pull',
            'operation': 'update',
        })

        with patch.object(
            self.env['qb.api.client'].__class__, 'get_client', return_value=client,
        ), patch.object(
            self.env['qb.sync.customers'].__class__, 'pull_all', return_value={'count': 1},
        ) as pull_all:
            self.env['qb.sync.engine'].execute_job(job)

        pull_all.assert_called_once_with(client, self.config, 'customer')

    def test_settings_save_does_not_auto_install_suggested_modules(self):
        settings = self.env['res.config.settings'].create({
            'company_id': self.company.id,
            'qb_sync_projects': True,
        })

        with patch.object(
            self.env['ir.module.module'].__class__, 'button_immediate_install',
        ) as install:
            settings.set_values()

        install.assert_not_called()

    def test_settings_suggestions_require_qbo_probe_data(self):
        settings = self.env['res.config.settings'].create({
            'company_id': self.company.id,
            'qb_sync_projects': True,
        })

        self.assertEqual(settings._suggest_modules_for_toggles(), [])

        self.env['quickbooks.data.probe'].create({
            'company_id': self.company.id,
            'area': 'projects',
            'has_data': True,
            'sample_count': 1,
        })
        self.assertIn('project', settings._suggest_modules_for_toggles())

    def test_data_probe_persists_qbo_data_presence(self):
        client = self._mock_client()
        client.query.return_value = {'QueryResponse': {'totalCount': 3}}

        probe = self.env['qb.data.probe'].run_area(
            self.config, client, 'purchase_orders',
        )

        self.assertTrue(probe.has_data)
        self.assertEqual(probe.sample_count, 3)
        self.assertEqual(probe.area, 'purchase_orders')

    def test_report_rows_are_normalized_from_nested_payload(self):
        payload = {
            'Header': {'ReportName': 'BalanceSheet'},
            'Rows': {
                'Row': [{
                    'Header': {'ColData': [{'value': 'Assets'}]},
                    'Rows': {'Row': [{
                        'ColData': [
                            {'value': 'Checking', 'id': '10'},
                            {'value': '1,234.56'},
                        ],
                    }]},
                }],
            },
        }

        rows = self.env['qb.sync.reports']._normalized_rows(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label'], 'Checking')
        self.assertEqual(rows[0]['id'], '10')
        self.assertEqual(rows[0]['amount'], 1234.56)

    def test_reports_client_builds_reports_endpoint(self):
        client = self.env['qb.api.client'].get_client(self.config)

        with patch.object(client, '_execute', return_value={}) as execute:
            client.reports(
                'BalanceSheet',
                params={'start_date': '2026-01-01', 'end_date': '2026-01-31'},
                testing_migration=True,
            )

        endpoint = execute.call_args[0][1]
        self.assertTrue(endpoint.startswith('reports/BalanceSheet?'))
        self.assertIn('start_date=2026-01-01', endpoint)
        self.assertIn('testing_migration=true', endpoint)

    def test_account_mapping_includes_qbo_balances(self):
        vals = self.env['qb.sync.accounts']._qb_account_to_odoo({
            'Id': '10',
            'Name': 'Checking',
            'AccountType': 'Bank',
            'OpeningBalance': 500.25,
            'OpeningBalanceDate': '2026-01-01',
            'CurrentBalance': 700.50,
            'CurrentBalanceWithSubAccounts': 725.75,
        })

        self.assertEqual(vals['qb_opening_balance'], 500.25)
        self.assertEqual(vals['qb_opening_balance_date'], '2026-01-01')
        self.assertEqual(vals['qb_current_balance'], 700.50)
        self.assertEqual(vals['qb_current_balance_with_subaccounts'], 725.75)

    def test_recurring_transaction_pull_upserts_template(self):
        client = self._mock_client()
        client.read.return_value = {
            'RecurringTransaction': {
                'Id': 'R1',
                'SyncToken': '0',
                'Name': 'Monthly Rent',
                'TxnType': 'Bill',
                'Active': True,
                'ScheduleInfo': {
                    'Type': 'Monthly',
                    'NextDate': '2026-02-01',
                    'IntervalInfo': {'Type': 'Month'},
                },
            },
        }
        job = self.env['quickbooks.sync.queue'].new({'qb_entity_id': 'R1'})

        self.env['qb.sync.recurring.transactions'].pull(client, self.config, job)

        template = self.env['quickbooks.recurring.template'].search([
            ('qb_recurring_id', '=', 'R1'),
        ], limit=1)
        self.assertEqual(template.name, 'Monthly Rent')
        self.assertEqual(template.txn_type, 'Bill')

    def test_custom_field_definition_upsert(self):
        definition = {
            'id': 'CF1',
            'name': 'Job Number',
            'type': 'TEXT',
            'active': True,
            'entityTypes': ['Invoice'],
        }

        record = self.env['qb.sync.custom.fields']._upsert_definition(
            self.config, definition,
        )

        self.assertEqual(record.qb_definition_id, 'CF1')
        self.assertEqual(record.name, 'Job Number')
        self.assertEqual(record.entity_type, 'Invoice')

    def test_payroll_client_keeps_existing_model_name(self):
        self.assertTrue(self.env['qb.payroll.client'])
        self.assertTrue(self.env['qb.graphql.client'])

    def test_employee_benefits_are_persisted_from_payroll_checks(self):
        data = {
            'payrollChecks': [{
                'id': 'PC1',
                'employeeId': 'E1',
                'displayName': 'Jane Doe',
                'payPeriodStart': '2026-01-01',
                'payPeriodEnd': '2026-01-15',
                'deductions': [{
                    'name': '401k Employee',
                    'type': 'Retirement',
                    'amount': 75.0,
                }],
            }],
        }

        count = self.env['qb.sync.employee.benefits']._upsert_benefits(
            self.config, data,
        )

        self.assertEqual(count, 1)
        benefit = self.env['quickbooks.employee.benefit'].search([
            ('source_check_id', '=', 'PC1'),
        ], limit=1)
        self.assertEqual(benefit.benefit_type, 'retirement')
        self.assertEqual(benefit.amount, 75.0)

    def test_workers_comp_class_manual_rate_estimate(self):
        workers_comp = self.env['quickbooks.workers.comp.class'].create({
            'company_id': self.company.id,
            'code': '8810',
            'name': 'Clerical Office Employees',
            'base_rate': 0.25,
        })

        self.assertEqual(workers_comp.source, 'manual')
        self.assertEqual(workers_comp.base_rate, 0.25)

    def test_hr_advisor_note_is_manual_only(self):
        note = self.env['quickbooks.hr.advisor.note'].create({
            'company_id': self.company.id,
            'name': 'Handbook update',
            'category': 'handbook',
        })

        self.assertEqual(note.api_status, 'manual')

    def test_payroll_settings_snapshot_created(self):
        self.config.payroll_enabled = True
        service = self.env['qb.sync.payroll.settings']

        with patch.object(
            self.env['qb.payroll.client'].__class__, 'fetch_pay_items',
            return_value={'payrollPayItems': [{'id': 'P1'}]},
        ), patch.object(
            self.env['qb.payroll.client'].__class__, 'fetch_pay_schedules',
            return_value={'payrollPaySchedules': [{'id': 'S1'}]},
        ), patch.object(service.__class__, '_work_locations', return_value={}):
            result = service.pull_all(self._mock_client(), self.config, 'payroll_settings')

        self.assertEqual(result['count'], 1)
        snapshot = self.env['quickbooks.payroll.settings'].search([], limit=1)
        self.assertTrue(snapshot.pay_items_json)

    def test_bank_rule_is_manual_only(self):
        rule = self.env['quickbooks.bank.rule'].create({
            'company_id': self.company.id,
            'name': 'Fuel purchases',
            'conditions_json': {'description_contains': 'FUEL'},
        })

        self.assertEqual(rule.api_status, 'manual')
        self.assertEqual(rule.conditions_json['description_contains'], 'FUEL')

    def test_qbo_group_item_maps_bundle_components_and_category(self):
        vals = self.env['qb.sync.products']._qb_item_to_odoo({
            'Id': 'G1',
            'Name': 'Starter Kit',
            'Type': 'Group',
            'ParentRef': {'value': 'CAT1', 'name': 'Kits'},
            'ItemGroupDetail': {
                'ItemGroupLine': [{
                    'ItemRef': {'value': 'I1', 'name': 'Widget'},
                    'Qty': 2,
                }],
            },
        })

        self.assertEqual(vals['qb_item_type'], 'Group')
        self.assertEqual(vals['qb_item_category_id'], 'CAT1')
        self.assertEqual(vals['qb_bundle_components'][0]['Qty'], 2)

    def test_attachment_target_supports_item_parent(self):
        product = self.env['product.product'].create({
            'name': 'Attachable Item',
            'qb_item_id': 'I1',
        })

        target = self.env['qb.sync.attachments']._find_odoo_target({
            'AttachableRef': [{
                'EntityRef': {'type': 'Item', 'value': product.qb_item_id},
            }],
        })

        self.assertEqual(target['res_model'], 'product.product')
        self.assertEqual(target['res_id'], product.id)
