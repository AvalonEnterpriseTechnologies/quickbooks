"""Smoke tests for the QuickBooks payroll bridge field surface.

Catches regressions where ``quickbooks_api_connector_hr_payroll`` ships with
``installable=False`` (the bug that originally caused the payroll sync
services to silently no-op). Each assertion is gated on the underlying
Odoo model so the suite skips cleanly when the optional Enterprise
modules are not present.
"""

from .common import QuickbooksTestCommon


REQUIRED_EMPLOYEE_FIELDS = {
    'qb_employee_id', 'qb_hired_date', 'qb_released_date', 'qb_employee_type',
    'qb_intuit_id', 'qb_employment_status', 'qb_termination_date',
    'qb_sync_token', 'qb_last_synced', 'qb_do_not_sync', 'qb_sync_error',
}

REQUIRED_EMPLOYEE_PAYROLL_FIELDS = {
    'qb_ssn_last4', 'qb_birth_date',
    'qb_federal_filing_status', 'qb_federal_multiple_jobs',
    'qb_federal_dependents_amount', 'qb_federal_other_income',
    'qb_federal_deductions', 'qb_federal_extra_withholding',
    'qb_federal_exempt', 'qb_state_w4_json', 'qb_direct_deposit_json',
    'qb_payroll_archived', 'qb_employee_classification',
}

REQUIRED_CONTRACT_FIELDS = {
    'qb_compensation_id', 'qb_employee_id', 'qb_pay_schedule_id',
    'qb_work_location_id', 'qb_employment_status', 'qb_rate', 'qb_rate_type',
    'qb_default_hours_per_week', 'qb_pay_schedule_record_id',
}

REQUIRED_SALARY_RULE_FIELDS = {
    'qb_pay_item_id', 'qb_pay_item_type', 'qb_pay_item_category',
    'qb_pay_item_calculation', 'qb_pay_item_tax_jurisdiction',
    'qb_gl_account_id', 'qb_liability_account_id', 'qb_vendor_id',
}

REQUIRED_STRUCTURE_FIELDS = {
    'qb_pay_schedule_id', 'qb_frequency', 'qb_next_pay_date',
}


class TestPayrollBridgeFieldsLoad(QuickbooksTestCommon):

    def assert_fields_loaded(self, model_name, required):
        if model_name not in self.env:
            self.skipTest('%s not installed' % model_name)
        model = self.env[model_name]
        missing = required - set(model._fields)
        self.assertFalse(
            missing,
            'Bridge fields missing on %s: %s. Has the '
            'quickbooks_api_connector_hr_payroll module been installed?'
            % (model_name, sorted(missing)),
        )

    def test_employee_hr_bridge_loaded(self):
        self.assert_fields_loaded('hr.employee', REQUIRED_EMPLOYEE_FIELDS)

    def test_employee_payroll_bridge_loaded(self):
        self.assert_fields_loaded(
            'hr.employee', REQUIRED_EMPLOYEE_PAYROLL_FIELDS,
        )

    def test_contract_bridge_loaded(self):
        self.assert_fields_loaded('hr.contract', REQUIRED_CONTRACT_FIELDS)

    def test_salary_rule_bridge_loaded(self):
        self.assert_fields_loaded(
            'hr.salary.rule', REQUIRED_SALARY_RULE_FIELDS,
        )

    def test_payroll_structure_bridge_loaded(self):
        self.assert_fields_loaded(
            'hr.payroll.structure', REQUIRED_STRUCTURE_FIELDS,
        )

    def test_archive_models_present(self):
        for model_name in ('qb.payroll.check', 'qb.payroll.check.line',
                           'qb.payroll.settings.snapshot'):
            if model_name not in self.env:
                self.skipTest('%s not installed' % model_name)
            self.assertTrue(self.env[model_name], '%s missing' % model_name)
