import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayroll(models.AbstractModel):
    _name = 'qb.sync.payroll'
    _description = 'QuickBooks Payroll Compensation Sync'

    def push(self, client, config, job):
        _logger.info('Payroll compensation is read from QBO and stored in Odoo.')
        return {}

    def pull(self, client, config, job):
        payroll_client = self.env['qb.payroll.client']
        try:
            data = payroll_client.fetch_compensations(config)
        except Exception:
            _logger.exception('Payroll compensation pull failed')
            return {}

        self._upsert_compensations(data, config)
        return {'qb_id': 'payroll_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        payroll_client = self.env['qb.payroll.client']
        try:
            data = payroll_client.fetch_compensations(config)
        except Exception:
            _logger.exception('Payroll compensation pull_all failed')
            return

        count = self._upsert_compensations(data, config)
        _logger.info('Pulled %d employee compensation records', count)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll compensation push_all; Payroll GraphQL is read-only here.')

    def _upsert_compensations(self, data, config):
        Compensation = self.env['quickbooks.payroll.compensation']
        count = 0
        for emp_comp in data.get('payrollEmployeeCompensations', []):
            qb_employee_id = str(emp_comp.get('employeeId', ''))
            employee = False
            if 'hr.employee' in self.env:
                employee = self.env['hr.employee'].search([
                    ('qb_employee_id', '=', qb_employee_id),
                ], limit=1)
            for comp in emp_comp.get('compensations', []):
                qb_comp_id = str(comp.get('id', ''))
                if not qb_employee_id or not qb_comp_id:
                    continue
                vals = {
                    'company_id': config.company_id.id,
                    'employee_id': employee.id if employee else False,
                    'qb_employee_id': qb_employee_id,
                    'qb_compensation_id': qb_comp_id,
                    'name': comp.get('name') or qb_comp_id,
                    'compensation_type': comp.get('type'),
                    'active': bool(comp.get('active', True)),
                    'qb_last_synced': fields.Datetime.now(),
                }
                existing = Compensation.search([
                    ('company_id', '=', config.company_id.id),
                    ('qb_employee_id', '=', qb_employee_id),
                    ('qb_compensation_id', '=', qb_comp_id),
                ], limit=1)
                if existing:
                    existing.write(vals)
                else:
                    Compensation.create(vals)
                count += 1
        return count
