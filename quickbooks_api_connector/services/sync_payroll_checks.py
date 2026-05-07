import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayrollChecks(models.AbstractModel):
    _name = 'qb.sync.payroll.checks'
    _description = 'QuickBooks Payroll Check Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll check push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_checks_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        data = self.env['qb.payroll.client'].fetch_checks(config)
        return self._upsert_checks(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll check push_all; Payroll GraphQL is read-only.')

    def cron_pull_for_all_companies(self):
        configs = self.env['quickbooks.config'].search([
            ('state', '=', 'connected'),
            ('payroll_enabled', '=', True),
        ])
        for config in configs:
            self.pull_all(None, config, 'payroll_check')

    def _upsert_checks(self, data, config):
        Check = self.env['quickbooks.payroll.check']
        count = 0
        for check in data.get('payrollChecks', []):
            qb_id = str(check.get('id') or '')
            if not qb_id:
                continue
            qb_employee_id = str(check.get('employeeId') or '')
            employee = self._find_employee(qb_employee_id)
            vals = {
                'company_id': config.company_id.id,
                'qb_check_id': qb_id,
                'qb_employee_id': qb_employee_id,
                'odoo_employee_id': employee.id if employee else False,
                'display_name': check.get('displayName') or qb_id,
                'check_date': check.get('checkDate') or False,
                'pay_period_start': check.get('payPeriodStart') or False,
                'pay_period_end': check.get('payPeriodEnd') or False,
                'gross_pay': float(check.get('grossPay') or 0.0),
                'net_pay': float(check.get('netPay') or 0.0),
                'status': check.get('status'),
                'qb_last_synced': fields.Datetime.now(),
            }
            existing = Check.search([
                ('company_id', '=', config.company_id.id),
                ('qb_check_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                existing = Check.create(vals)
            if getattr(config, 'payroll_create_draft_payslips', False):
                self._ensure_draft_payslip(existing, employee)
            count += 1
        return count

    def _find_employee(self, qb_employee_id):
        if not qb_employee_id or 'hr.employee' not in self.env:
            return False
        return self.env['hr.employee'].search([
            ('qb_employee_id', '=', qb_employee_id),
        ], limit=1)

    def _ensure_draft_payslip(self, check, employee):
        if not employee or 'hr.payslip' not in self.env or check.odoo_payslip_id:
            return
        vals = {
            'employee_id': employee.id,
            'name': check.display_name,
            'date_from': check.pay_period_start or check.check_date,
            'date_to': check.pay_period_end or check.check_date,
            'company_id': check.company_id.id,
        }
        payslip = self.env['hr.payslip'].create(vals)
        check.write({'odoo_payslip_id': payslip.id})
