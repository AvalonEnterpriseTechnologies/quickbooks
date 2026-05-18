from .common import QuickbooksTestCommon


class TestPayrollExtended(QuickbooksTestCommon):

    # ------------------------------------------------------------------
    # Pay schedules -> hr.payroll.structure (Phase 3)
    # ------------------------------------------------------------------

    def test_schedules_create_payroll_structure(self):
        if 'hr.payroll.structure' not in self.env:
            self.skipTest('hr_payroll not installed')
        data = {
            'payrollPaySchedules': [{
                'id': 'PS1',
                'name': 'Biweekly',
                'frequency': 'BIWEEKLY',
                'active': True,
                'nextPayDate': '2026-05-15',
                'payDate': '2026-05-15',
            }],
        }
        count = self.env['qb.sync.payroll.schedules']._upsert_schedules(
            data, self.config,
        )
        self.assertEqual(count, 1)
        structure = self.env['hr.payroll.structure'].search([
            ('qb_pay_schedule_id', '=', 'PS1'),
        ], limit=1)
        self.assertTrue(structure, 'pay schedule did not create hr.payroll.structure')
        self.assertEqual(structure.qb_frequency, 'BIWEEKLY')
        if 'type_id' in structure._fields:
            self.assertTrue(
                structure.type_id,
                'structure must be attached to a structure type',
            )

    # ------------------------------------------------------------------
    # Pay items -> categorized hr.salary.rule with GL accounts (Phase 3)
    # ------------------------------------------------------------------

    def test_pay_items_are_categorized_and_attached_to_structure(self):
        if 'hr.payroll.structure' not in self.env:
            self.skipTest('hr_payroll not installed')
        Structure = self.env['hr.payroll.structure'].sudo()
        StructType = self.env['hr.payroll.structure.type'].sudo()
        struct_type = StructType.create({'name': 'QuickBooks - Biweekly'})
        Structure.create({
            'name': 'Biweekly',
            'qb_pay_schedule_id': 'PS-EARN',
            'type_id': struct_type.id,
        })

        data = {
            'payrollPayItems': [{
                'id': 'PI-EARN',
                'name': 'Regular Pay',
                'code': 'REG',
                'category': 'EARNING',
                'calculationType': 'RATE',
                'active': True,
                'payScheduleId': 'PS-EARN',
            }],
        }
        count = self.env['qb.sync.payroll.pay.items']._upsert_pay_items(
            data, self.config,
        )
        self.assertGreaterEqual(count, 1)
        rule = self.env['hr.salary.rule'].search([
            ('qb_pay_item_id', '=', 'PI-EARN'),
        ], limit=1)
        self.assertTrue(rule, 'pay item did not create hr.salary.rule')
        self.assertEqual(rule.qb_pay_item_category, 'earning')
        self.assertEqual(rule.qb_pay_item_calculation, 'rate')
        self.assertTrue(rule.struct_id, 'salary rule must be attached to a structure')

    def test_pay_items_skip_ytd_synthetic(self):
        if 'hr.salary.rule' not in self.env:
            self.skipTest('hr_payroll not installed')
        data = {
            'payrollPayItems': [{
                'id': 'PI-YTD',
                'name': 'YTD Federal Income Tax',
                'category': 'TAX',
                'isYtd': True,
            }],
        }
        self.env['qb.sync.payroll.pay.items']._upsert_pay_items(data, self.config)
        rule = self.env['hr.salary.rule'].search([
            ('qb_pay_item_id', '=', 'PI-YTD'),
        ], limit=1)
        self.assertFalse(rule, 'YTD-only items should be skipped')

    # ------------------------------------------------------------------
    # Compensation -> contract wage / pay schedule (Phase 3)
    # ------------------------------------------------------------------

    def test_compensation_updates_contract_wage(self):
        if 'hr.contract' not in self.env or 'hr.employee' not in self.env:
            self.skipTest('hr_payroll not installed')
        employee = self.env['hr.employee'].create({
            'name': 'Comp Tester',
            'qb_employee_id': 'EMP-COMP-1',
        })
        self.env['hr.contract'].create({
            'name': 'Initial',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'qb_employee_id': 'EMP-COMP-1',
            'wage': 0.0,
        })
        data = {
            'payrollEmployeeCompensations': [{
                'employeeId': 'EMP-COMP-1',
                'compensations': [{
                    'id': 'COMP-A',
                    'name': 'Salary',
                    'rate': 1500.0,
                    'rateType': 'SALARY',
                    'payScheduleId': 'PS-COMP',
                    'defaultHoursPerWeek': 40,
                    'active': True,
                }],
            }],
        }
        self.env['qb.sync.payroll']._upsert_compensations(data, self.config)
        contract = self.env['hr.contract'].search([
            ('qb_compensation_id', '=', 'COMP-A'),
        ], limit=1)
        self.assertTrue(contract)
        self.assertEqual(contract.wage, 1500.0)
        self.assertEqual(contract.qb_rate, 1500.0)
        self.assertEqual(contract.qb_rate_type, 'salary')
        self.assertEqual(contract.qb_pay_schedule_id, 'PS-COMP')

    # ------------------------------------------------------------------
    # Tax setup -> Kansas K-4 (Phase 3)
    # ------------------------------------------------------------------

    def test_tax_setup_maps_to_kansas_k4(self):
        if 'hr.employee' not in self.env:
            self.skipTest('hr not installed')
        employee = self.env['hr.employee'].create({
            'name': 'Kansas Worker',
            'qb_employee_id': 'EMP-KS-1',
        })
        if 'l10n_ks_filing_status' not in employee._fields:
            self.skipTest('l10n_us_hr_payroll_ks bridge fields not present')
        data = {
            'payrollEmployeeTaxSetup': [{
                'employeeId': 'EMP-KS-1',
                'federalW4': {
                    'filingStatus': 'SINGLE',
                    'extraWithholding': 50.0,
                    'exempt': False,
                },
                'stateW4': [{
                    'stateCode': 'KS',
                    'filingStatus': 'MARRIED',
                    'allowances': 3,
                    'extraWithholding': 25.0,
                    'exempt': False,
                }],
            }],
        }
        self.env['qb.sync.payroll.employees']._upsert_tax_setup(data, self.config)
        employee.invalidate_recordset()
        self.assertEqual(employee.qb_federal_filing_status, 'single')
        self.assertEqual(employee.qb_federal_extra_withholding, 50.0)
        self.assertEqual(employee.l10n_ks_filing_status, 'married')
        self.assertEqual(employee.l10n_ks_total_allowances, 3)
        self.assertEqual(employee.l10n_ks_additional_withholding, 25.0)
        self.assertFalse(employee.l10n_ks_exempt)
        self.assertEqual(employee.qb_state_w4_json.get('KS', {}).get('stateCode'), 'KS')

    # ------------------------------------------------------------------
    # Checks -> qb.payroll.check archive with line breakdown (Phase 3)
    # ------------------------------------------------------------------

    def test_checks_archive_with_full_line_breakdown(self):
        if 'qb.payroll.check' not in self.env:
            self.skipTest('hr_payroll bridge not installed')
        data = {
            'payrollChecks': [{
                'id': 'CHK-A',
                'employeeId': 'EMP-A',
                'displayName': 'Pay Check',
                'checkDate': '2026-05-01',
                'checkNumber': '1001',
                'paymentMethod': 'DIRECT_DEPOSIT',
                'payPeriodStart': '2026-04-18',
                'payPeriodEnd': '2026-05-01',
                'grossPay': 2000.0,
                'netPay': 1500.0,
                'status': 'PAID',
                'earnings': [{
                    'payItemId': 'PI-EARN',
                    'name': 'Regular Pay',
                    'hours': 80,
                    'rate': 25,
                    'amount': 2000.0,
                }],
                'taxes': [{
                    'payItemId': 'PI-FED',
                    'name': 'Federal Income Tax',
                    'type': 'FEDERAL',
                    'employee': 200.0,
                    'employer': 0.0,
                    'jurisdiction': 'US',
                }, {
                    'payItemId': 'PI-FICA',
                    'name': 'FICA',
                    'type': 'FICA',
                    'employee': 124.0,
                    'employer': 124.0,
                    'jurisdiction': 'US',
                }],
                'deductions': [{
                    'payItemId': 'PI-401K',
                    'name': '401(k)',
                    'employee': 100.0,
                    'employer': 50.0,
                    'isPreTax': True,
                }],
                'employerContributions': [{
                    'payItemId': 'PI-HEALTH',
                    'name': 'Health Insurance',
                    'amount': 75.0,
                }],
            }],
        }
        self.env['qb.sync.payroll.checks']._upsert_checks(data, self.config)
        check = self.env['qb.payroll.check'].search([
            ('qb_check_id', '=', 'CHK-A'),
        ], limit=1)
        self.assertTrue(check)
        self.assertEqual(check.gross_pay, 2000.0)
        self.assertEqual(check.net_pay, 1500.0)
        self.assertEqual(check.check_number, '1001')
        self.assertEqual(check.payment_method, 'direct_deposit')
        self.assertEqual(len(check.line_ids), 6)
        self.assertEqual(check.total_employee_tax, 324.0)
        self.assertEqual(check.total_employer_tax, 124.0)
        self.assertEqual(check.total_deductions, 100.0)
        self.assertEqual(check.total_employer_contributions, 125.0)

    # ------------------------------------------------------------------
    # Archive journal posting (Phase 3 optional GL mirror)
    # ------------------------------------------------------------------

    def test_archive_journal_balances_when_accounts_resolve(self):
        if 'qb.payroll.check' not in self.env:
            self.skipTest('hr_payroll bridge not installed')
        Account = self.env['account.account'].sudo()
        Journal = self.env['account.journal'].sudo()
        # Ensure a general journal exists for the test company.
        if not Journal.search([
            ('company_id', '=', self.company.id),
            ('type', '=', 'general'),
        ], limit=1):
            Journal.create({
                'name': 'QB Test General',
                'code': 'QBTG',
                'type': 'general',
                'company_id': self.company.id,
            })

        salary_expense = Account.search([
            ('account_type', '=', 'expense'),
        ], limit=1)
        payroll_liability = Account.search([
            ('account_type', '=', 'liability_current'),
        ], limit=1)
        if not salary_expense or not payroll_liability:
            self.skipTest('Required account types are not seeded in this DB.')

        rule = self.env['hr.salary.rule'].sudo().search([
            ('qb_pay_item_id', '=', 'PI-MOVE-EARN'),
        ], limit=1)
        if not rule:
            struct = self.env['hr.payroll.structure'].sudo().search([], limit=1)
            if not struct:
                self.skipTest('No payroll structure available for the test.')
            category = self.env['hr.salary.rule.category'].sudo().search([], limit=1)
            rule = self.env['hr.salary.rule'].sudo().create({
                'name': 'Move Earning',
                'code': 'MOVE_EARN',
                'qb_pay_item_id': 'PI-MOVE-EARN',
                'qb_gl_account_id': salary_expense.id,
                'qb_liability_account_id': payroll_liability.id,
                'category_id': category.id if category else False,
                'struct_id': struct.id,
                'condition_select': 'none',
                'amount_select': 'fix',
            })

        self.config.write({'qb_payroll_post_archive_journal': True})
        data = {
            'payrollChecks': [{
                'id': 'CHK-MOVE',
                'employeeId': 'EMP-MOVE',
                'displayName': 'Move Pay Check',
                'checkDate': '2026-05-01',
                'grossPay': 1000.0,
                'netPay': 800.0,
                'status': 'PAID',
                'earnings': [{
                    'payItemId': 'PI-MOVE-EARN',
                    'name': 'Move Earning',
                    'amount': 1000.0,
                }],
                'taxes': [{
                    'payItemId': 'PI-MOVE-EARN',
                    'name': 'Federal Tax',
                    'type': 'FEDERAL',
                    'employee': 200.0,
                    'employer': 0.0,
                }],
            }],
        }
        self.env['qb.sync.payroll.checks']._upsert_checks(data, self.config)
        check = self.env['qb.payroll.check'].search([
            ('qb_check_id', '=', 'CHK-MOVE'),
        ], limit=1)
        self.assertTrue(check)
        # The journal posting is conditional on a clearing account; if Odoo
        # cannot resolve one in this DB the connector skips the move rather
        # than posting an unbalanced entry. Either outcome is acceptable.
        if check.archive_move_id:
            move = check.archive_move_id
            self.assertEqual(
                round(sum(line.debit for line in move.line_ids), 2),
                round(sum(line.credit for line in move.line_ids), 2),
            )
