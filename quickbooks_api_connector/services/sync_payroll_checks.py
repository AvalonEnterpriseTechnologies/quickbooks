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
        if 'hr.payslip' not in self.env:
            _logger.warning("hr_payroll module not installed — skipping payroll check sync")
            return 0
        Payslip = self.env['hr.payslip'].sudo()
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
                'employee_id': employee.id if employee else False,
                'name': check.get('displayName') or qb_id,
                'date_from': check.get('payPeriodStart') or check.get('checkDate') or False,
                'date_to': check.get('payPeriodEnd') or check.get('checkDate') or False,
                'qb_gross_pay': float(check.get('grossPay') or 0.0),
                'qb_net_pay': float(check.get('netPay') or 0.0),
                'qb_status': check.get('status'),
                'qb_last_synced': fields.Datetime.now(),
                'qb_raw_json': check,
            }
            vals = {key: value for key, value in vals.items() if key in Payslip._fields}
            existing = Payslip.search([
                ('company_id', '=', config.company_id.id),
                ('qb_check_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Payslip.create(vals)
            count += 1
        return count

    def _find_employee(self, qb_employee_id):
        if not qb_employee_id or 'hr.employee' not in self.env:
            return False
        return self.env['hr.employee'].search([
            ('qb_employee_id', '=', qb_employee_id),
        ], limit=1)

