"""End-to-end coverage for the 19.0.8 → 19.0.11 QBO migration fixes.

Each test gates on the optional Odoo modules it needs (``hr``,
``hr_payroll``) via ``skipTest`` so the suite stays green on Community
deployments where those modules are absent. Together they cover:

  * ``qb.record.matcher`` employee branch (email + SSN-last-4 + phone +
    normalized-name) so the migration stops creating duplicates.
  * ``qb.sync.payroll.employees`` routing every incoming row through the
    central matcher instead of always creating fresh hr.employee rows.
  * Per-account journal routing in ``qb.sync.journal.entries`` via
    ``qb.sync.journals.ensure_general_journal_for_account``.
  * ``qb.sync.accounts.get_or_create_from_qb_id`` honoring the
    ``account_strategy`` toggle (link existing / create new / refuse to
    create) and being idempotent on re-reads.
  * ``qb.sync.payroll.payslips`` backfill being idempotent on
    ``qb_check_id`` and projecting QBO checks into hr.payslip +
    hr.payslip.run posted as ``done``.
  * ``quickbooks.config.action_qb_enable_payroll_all`` flipping every
    payroll toggle on without exploding when the underlying modules are
    missing.
  * ``qb.sync.engine.run_full_sync`` calling
    ``config._run_account_discovery(write_links=True)`` after the
    account stage and before any other stage that depends on the
    mapping (auto-apply mapping ordering).
"""

from unittest.mock import MagicMock, patch

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestEmployeeMatcher(QuickbooksTestCommon):

    def _Employee(self):
        if 'hr.employee' not in self.env:
            self.skipTest('hr module not installed')
        return self.env['hr.employee']

    def test_match_by_work_email_exact_normalized(self):
        Employee = self._Employee()
        existing = Employee.with_context(skip_qb_sync=True).create({
            'name': 'Person A',
            'work_email': 'shared@example.com',
        })
        qb_data = {
            'Id': '9001',
            'DisplayName': 'Wildly Different Name',
            'PrimaryEmailAddr': {'Address': 'SHARED@EXAMPLE.COM'},
        }
        match = self.env['qb.record.matcher'].find_odoo_match(
            'employee', qb_data, self.company,
        )
        self.assertEqual(match, existing,
                         'Email match must be case-insensitive')

    def test_match_by_ssn_last4_when_field_present(self):
        Employee = self._Employee()
        if 'qb_ssn_last4' not in Employee._fields:
            self.skipTest('qb_ssn_last4 not present (hr_payroll bridge missing)')
        existing = Employee.with_context(skip_qb_sync=True).create({
            'name': 'Person B',
            'qb_ssn_last4': '1234',
        })
        qb_data = {
            'Id': '9002',
            'DisplayName': 'Totally Different Person',
            'SSN': '999-99-1234',
        }
        match = self.env['qb.record.matcher'].find_odoo_match(
            'employee', qb_data, self.company,
        )
        self.assertEqual(match, existing,
                         'SSN last-4 match must beat name mismatch')

    def test_match_by_normalized_name_when_no_email_or_ssn(self):
        Employee = self._Employee()
        existing = Employee.with_context(skip_qb_sync=True).create({
            'name': 'Jane   Q.   Public',
        })
        qb_data = {
            'Id': '9003',
            'GivenName': 'jane q.',
            'FamilyName': 'public',
        }
        match = self.env['qb.record.matcher'].find_odoo_match(
            'employee', qb_data, self.company,
        )
        self.assertEqual(match, existing,
                         'Normalized name comparison must collapse whitespace + casefold')

    def test_match_by_phone_when_field_present(self):
        Employee = self._Employee()
        if 'work_phone' not in Employee._fields:
            self.skipTest('hr.employee.work_phone missing')
        existing = Employee.with_context(skip_qb_sync=True).create({
            'name': 'Different Name Entirely',
            'work_phone': '(555) 123-4567',
        })
        qb_data = {
            'Id': '9004',
            'DisplayName': 'Nope',
            'PrimaryPhone': {'FreeFormNumber': '+1 555.123.4567'},
        }
        match = self.env['qb.record.matcher'].find_odoo_match(
            'employee', qb_data, self.company,
        )
        self.assertEqual(match, existing,
                         'Phone normalization must ignore formatting and US country code')

    def test_no_match_returns_empty_recordset(self):
        Employee = self._Employee()
        qb_data = {
            'Id': '9099',
            'DisplayName': 'Completely Unknown Newcomer',
            'PrimaryEmailAddr': {'Address': 'never-seen@example.com'},
        }
        match = self.env['qb.record.matcher'].find_odoo_match(
            'employee', qb_data, self.company,
        )
        self.assertFalse(match)


@tagged('post_install', '-at_install')
class TestPayrollEmployeesViaMatcher(QuickbooksTestCommon):
    """sync_payroll_employees must reuse existing hr.employee rows instead
    of creating fresh duplicates for every GraphQL pull.
    """

    def setUp(self):
        super().setUp()
        if 'hr.employee' not in self.env:
            self.skipTest('hr module not installed')
        if 'qb.sync.payroll.employees' not in self.env:
            self.skipTest('Payroll bridge missing qb.sync.payroll.employees')
        self.config.payroll_enabled = True

    def _gql_employee(self, qb_id, email, name='Match Me'):
        return {
            'id': qb_id,
            'displayName': name,
            'givenName': name.split()[0],
            'familyName': ' '.join(name.split()[1:]) or '',
            'email': email,
            'active': True,
        }

    def test_existing_employee_is_linked_not_duplicated(self):
        existing = self.env['hr.employee'].with_context(
            skip_qb_sync=True,
        ).create({
            'name': 'Match Me',
            'work_email': 'match@example.com',
        })
        service = self.env['qb.sync.payroll.employees']
        Helper = service._find_or_create_employee
        helper_resolved = Helper(
            self._gql_employee('paygql-1', 'match@example.com'),
            self.config,
        )
        self.assertEqual(
            helper_resolved.id, existing.id,
            'Payroll pull must reuse the matching hr.employee row',
        )
        self.assertEqual(
            helper_resolved.qb_employee_id, 'paygql-1',
            'Payroll pull must link qb_employee_id when matching by email',
        )
        # Re-running with the same payload must not create a second row.
        second = Helper(
            self._gql_employee('paygql-1', 'match@example.com'),
            self.config,
        )
        self.assertEqual(second.id, existing.id)


@tagged('post_install', '-at_install')
class TestPerAccountJournalRouting(QuickbooksTestCommon):
    """A QBO JE must land in a per-account general journal derived from
    its dominant (largest |amount|) debit/credit line, never in the
    legacy single 'QuickBooks Journal Entries' bucket.
    """

    def _make_account(self, code, name, qb_id, account_type='asset_cash'):
        return self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': name,
            'code': code,
            'account_type': account_type,
            'qb_account_id': qb_id,
        })

    def test_je_routes_to_per_account_journal_for_dominant_line(self):
        cash = self._make_account('1090', 'QBO Cash', '10')
        revenue = self._make_account(
            '4090', 'QBO Revenue', '20', account_type='income',
        )
        service = self.env['qb.sync.journal.entries']
        qb_data = self._make_qb_journal_entry()['JournalEntry']
        vals = service._qb_je_to_odoo(qb_data, self.config)
        Journal = self.env['account.journal']
        journal = Journal.browse(vals['journal_id'])
        self.assertEqual(journal.type, 'general')
        self.assertTrue(journal.qb_journal_key.startswith('qbo:general:account:'),
                        'JE must route to a per-account general journal')
        # Both lines have equal amounts (1000.00); whichever the resolver
        # picked, it must be one of the two anchor accounts.
        self.assertIn(journal.qb_journal_key,
                      ('qbo:general:account:10', 'qbo:general:account:20'))
        # Make sure the per-account journal is created lazily (it didn't
        # exist before the resolver ran).
        existing = Journal.search([
            ('company_id', '=', self.company.id),
            ('qb_journal_key', '=', journal.qb_journal_key),
        ])
        self.assertEqual(len(existing), 1)

    def test_per_account_journal_lookup_is_idempotent(self):
        SyncJournals = self.env['qb.sync.journals']
        account = self._make_account('1091', 'QBO Cash 91', '11')
        first = SyncJournals.ensure_general_journal_for_account(
            self.config, account,
        )
        second = SyncJournals.ensure_general_journal_for_account(
            self.config, account,
        )
        self.assertEqual(first.id, second.id,
                         'Same account must always resolve to the same journal')


@tagged('post_install', '-at_install')
class TestGetOrCreateAccountFromQbId(QuickbooksTestCommon):

    def _qb_account_payload(self, qb_id='401', name='Test Auto Account'):
        return {
            'Account': {
                'Id': qb_id,
                'SyncToken': '0',
                'Name': name,
                'AccountType': 'Expense',
                'Active': True,
                'AcctNum': '7777',
                'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
            }
        }

    def test_returns_existing_account_without_calling_qbo(self):
        existing = self.env['account.account'].with_context(skip_qb_sync=True).create({
            'name': 'Already Linked',
            'code': '7788',
            'account_type': 'expense',
            'qb_account_id': '500',
        })
        client = self._mock_client()
        result = self.env['qb.sync.accounts'].get_or_create_from_qb_id(
            self.config, '500', client=client,
        )
        self.assertEqual(result, existing)
        client.read.assert_not_called()

    def test_create_missing_strategy_creates_account_on_demand(self):
        self.config.account_strategy = 'create_missing'
        client = self._mock_client()
        client.read.return_value = self._qb_account_payload('501', 'Created From Helper')

        result = self.env['qb.sync.accounts'].get_or_create_from_qb_id(
            self.config, '501', client=client,
        )
        self.assertTrue(result)
        self.assertEqual(result.qb_account_id, '501')
        client.read.assert_called_once_with('Account', '501')

        # Idempotent: second call must reuse the just-created row.
        client.read.reset_mock()
        again = self.env['qb.sync.accounts'].get_or_create_from_qb_id(
            self.config, '501', client=client,
        )
        self.assertEqual(again, result)
        client.read.assert_not_called()

    def test_map_only_strategy_refuses_to_create(self):
        self.config.account_strategy = 'map_only'
        client = self._mock_client()
        client.read.return_value = self._qb_account_payload('502', 'Refused By Strategy')

        result = self.env['qb.sync.accounts'].get_or_create_from_qb_id(
            self.config, '502', client=client,
        )
        self.assertFalse(result,
                         'map_only must return an empty recordset for unmatched accounts')


@tagged('post_install', '-at_install')
class TestPayslipBackfillIdempotency(QuickbooksTestCommon):

    def setUp(self):
        super().setUp()
        if 'hr.payslip' not in self.env:
            self.skipTest('hr_payroll bridge not installed')
        if 'qb.payroll.check' not in self.env:
            self.skipTest('QBO payroll archive missing')
        if 'qb_check_id' not in self.env['hr.payslip']._fields:
            self.skipTest('hr.payslip QBO bridge fields missing')
        self.config.payroll_enabled = True
        self.config.sync_payroll_payslips = True

    def _make_employee(self):
        return self.env['hr.employee'].with_context(skip_qb_sync=True).create({
            'name': 'Backfill Person',
            'work_email': 'backfill@example.com',
            'qb_employee_id': 'qbo-emp-700',
        })

    def _make_check(self, employee, qb_check_id='qbo-check-1', amount=1000.0):
        return self.env['qb.payroll.check'].sudo().create({
            'company_id': self.company.id,
            'qb_check_id': qb_check_id,
            'qb_employee_id': employee.qb_employee_id,
            'employee_id': employee.id,
            'check_date': '2026-01-15',
            'period_start': '2026-01-01',
            'period_end': '2026-01-15',
            'gross_pay': amount,
            'net_pay': amount * 0.8,
            'status': 'paid',
        })

    def test_payslip_backfill_creates_and_does_not_duplicate(self):
        employee = self._make_employee()
        self._make_check(employee, 'qbo-check-1')
        self._make_check(employee, 'qbo-check-2')

        service = self.env['qb.sync.payroll.payslips']
        first_run = service.pull_all(None, self.config, 'payroll_payslip')
        self.assertEqual(first_run, 2)

        Payslip = self.env['hr.payslip']
        Run = self.env['hr.payslip.run']
        slips = Payslip.search([('qb_check_id', 'in', ['qbo-check-1', 'qbo-check-2'])])
        self.assertEqual(len(slips), 2)
        runs = Run.search([('qb_payslip_run_id', '!=', False),
                          ('company_id', '=', self.company.id)])
        self.assertEqual(len(runs), 1,
                         'Both checks share period -> single payslip batch')

        # Re-run: must NOT create new rows (idempotent on qb_check_id +
        # qb_payslip_run_id).
        service.pull_all(None, self.config, 'payroll_payslip')
        slips_after = Payslip.search([('qb_check_id', 'in', ['qbo-check-1', 'qbo-check-2'])])
        self.assertEqual(len(slips_after), 2)
        runs_after = Run.search([('qb_payslip_run_id', '!=', False),
                                ('company_id', '=', self.company.id)])
        self.assertEqual(len(runs_after), 1)


@tagged('post_install', '-at_install')
class TestEnablePayrollAction(QuickbooksTestCommon):

    def test_action_enables_every_payroll_toggle(self):
        self.config.payroll_enabled = False
        self.config.sync_payroll_pay_items = False
        self.config.sync_payroll_employees = False
        self.config.sync_payroll_checks = False
        self.config.sync_payroll_payslips = False

        with patch.object(
            type(self.env['ir.module.module']), 'button_immediate_install',
            return_value=True,
        ), patch.object(
            type(self.env['qb.sync.payroll.orchestrator']), 'pull_for_config',
            return_value=True,
        ):
            self.config.action_qb_enable_payroll_all()

        self.assertTrue(self.config.payroll_enabled)
        self.assertTrue(self.config.sync_payroll_pay_items)
        self.assertTrue(self.config.sync_payroll_employees)
        self.assertTrue(self.config.sync_payroll_checks)
        self.assertTrue(self.config.sync_payroll_payslips)


@tagged('post_install', '-at_install')
class TestAutoApplyMappingOrdering(QuickbooksTestCommon):
    """run_full_sync must invoke config._run_account_discovery(write_links=True)
    immediately AFTER the 'account' stage and BEFORE every downstream stage
    that reads from the QBO->Odoo account mapping.
    """

    def _disable_every_sync_toggle(self):
        for fname, fobj in type(self.config)._fields.items():
            if fname.startswith('sync_') and fobj.type == 'boolean':
                try:
                    setattr(self.config, fname, False)
                except Exception:
                    pass
        self.config.payroll_enabled = False
        self.config.qbt_enabled = False
        if 'custom_fields_enabled' in type(self.config)._fields:
            self.config.custom_fields_enabled = False

    def _run_full_sync_with_capture(self, qb_auto_apply):
        """Drive run_full_sync against stubbed services so we can observe
        the call ordering between qb.sync.accounts.pull_all and
        quickbooks.config._run_account_discovery.

        Only qb.sync.accounts is stubbed (it is the one stage that
        precedes the account-discovery hook). Every other entity is
        disabled via toggle_map so the engine never reaches its
        pull_all/push_all.
        """
        self.config.qb_auto_apply_account_mapping = qb_auto_apply
        self._disable_every_sync_toggle()

        engine = self.env['qb.sync.engine']
        captured = []
        Accounts = type(self.env['qb.sync.accounts'])
        Client = type(self.env['qb.api.client'])
        Config = type(self.config)

        def _capture_account_pull(self_service, client, config, entity_type):
            captured.append(('account_pull', entity_type))

        def _capture_account_push(self_service, client, config, entity_type):
            captured.append(('account_push', entity_type))

        def _capture_discovery(self_config, write_links=True):
            captured.append(('discovery', write_links))

        with patch.object(Accounts, 'pull_all', _capture_account_pull), \
             patch.object(Accounts, 'push_all', _capture_account_push), \
             patch.object(Config, '_run_account_discovery', _capture_discovery), \
             patch.object(Client, 'get_client', return_value=self._mock_client()), \
             patch.object(engine, '_collect_cdc_records', return_value={}):
            engine.run_full_sync(self.config)
        return captured

    def test_run_account_discovery_called_after_account_stage(self):
        captured = self._run_full_sync_with_capture(qb_auto_apply=True)
        self.assertIn(('account_pull', 'account'), captured)
        discovery_idx = next(
            (i for i, ev in enumerate(captured) if ev[0] == 'discovery'),
            None,
        )
        self.assertIsNotNone(
            discovery_idx,
            '_run_account_discovery must be called after the account stage',
        )
        account_idx = next(
            i for i, ev in enumerate(captured)
            if ev == ('account_pull', 'account')
        )
        self.assertLess(
            account_idx, discovery_idx,
            'discovery must run AFTER the account pull',
        )

    def test_discovery_skipped_when_auto_apply_disabled(self):
        captured = self._run_full_sync_with_capture(qb_auto_apply=False)
        discovery_events = [ev for ev in captured if ev[0] == 'discovery']
        self.assertFalse(
            discovery_events,
            'discovery must NOT run when qb_auto_apply_account_mapping is False',
        )
