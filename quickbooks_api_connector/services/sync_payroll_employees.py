import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayrollEmployees(models.AbstractModel):
    _name = 'qb.sync.payroll.employees'
    _description = 'QuickBooks Payroll Employee Cache Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll employee push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_employees_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        data = self.env['qb.payroll.client'].fetch_payroll_employees(config)
        return self._upsert_employees(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll employee push_all; Payroll GraphQL is read-only.')

    def _upsert_employees(self, data, config):
        count = 0
        for employee in data.get('payrollEmployees', []):
            qb_id = str(employee.get('id') or '')
            if not qb_id:
                continue
            odoo_employee = self._find_employee(qb_id)
            if odoo_employee:
                self._update_hr_employee(odoo_employee, employee)
                self._update_contract(odoo_employee, employee, config)
            count += 1
        return count

    def _find_employee(self, qb_employee_id):
        if 'hr.employee' not in self.env:
            return False
        if 'qb_employee_id' not in self.env['hr.employee']._fields:
            return False
        return self.env['hr.employee'].search([
            ('qb_employee_id', '=', qb_employee_id),
        ], limit=1)

    def _update_hr_employee(self, employee, data):
        vals = {}
        if 'qb_employment_status' in employee._fields:
            vals['qb_employment_status'] = self._normalize_status(
                data.get('employmentStatus')
            )
        if 'qb_termination_date' in employee._fields:
            vals['qb_termination_date'] = data.get('terminationDate') or False
        if 'qb_hired_date' in employee._fields:
            vals['qb_hired_date'] = data.get('hireDate') or False
        if vals:
            employee.with_context(skip_qb_sync=True).write(vals)

    def _update_contract(self, employee, data, config):
        if 'hr.contract' not in self.env:
            return False
        Contract = self.env['hr.contract'].sudo()
        if 'qb_employee_id' not in Contract._fields:
            return False
        contract = Contract.search([
            ('employee_id', '=', employee.id),
            ('company_id', '=', config.company_id.id),
        ], order='date_start desc, id desc', limit=1)
        vals = {
            'name': employee.name,
            'employee_id': employee.id,
            'company_id': config.company_id.id,
            'qb_employee_id': data.get('id') or employee.qb_employee_id,
            'qb_work_location_id': data.get('workLocationId') or False,
            'qb_pay_schedule_id': data.get('payScheduleId') or False,
            'qb_employment_status': data.get('employmentStatus') or False,
            'date_start': data.get('hireDate') or fields.Date.context_today(self),
            'qb_last_synced': fields.Datetime.now(),
            'qb_raw_json': data,
        }
        vals = {key: value for key, value in vals.items() if key in Contract._fields}
        if contract:
            contract.write(vals)
            return contract
        return Contract.create(vals)

    @staticmethod
    def _normalize_status(status):
        status = str(status or '').lower()
        if 'term' in status:
            return 'terminated'
        if 'leave' in status:
            return 'leave'
        if 'inactive' in status:
            return 'inactive'
        return 'active'
