import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayroll(models.AbstractModel):
    _name = 'qb.sync.payroll'
    _description = 'QuickBooks Payroll Compensation Sync'

    def push(self, client, config, job):
        return {}

    def pull(self, client, config, job):
        payroll_client = self.env['qb.payroll.client']
        try:
            data = payroll_client.fetch_compensations(config)
        except Exception:
            _logger.exception('Payroll compensation pull failed')
            return {}

        compensations = data.get('payrollEmployeeCompensations', [])
        for emp_comp in compensations:
            emp_id = emp_comp.get('employeeId')
            comps = emp_comp.get('compensations', [])
            _logger.info(
                'Employee %s has %d compensation types', emp_id, len(comps),
            )
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

        compensations = data.get('payrollEmployeeCompensations', [])
        _logger.info('Pulled %d employee compensation records', len(compensations))

    def push_all(self, client, config, entity_type):
        pass
