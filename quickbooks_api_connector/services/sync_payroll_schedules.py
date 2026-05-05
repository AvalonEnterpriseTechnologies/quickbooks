import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayrollSchedules(models.AbstractModel):
    _name = 'qb.sync.payroll.schedules'
    _description = 'QuickBooks Payroll Pay Schedule Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll schedule push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_schedules_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        data = self.env['qb.payroll.client'].fetch_pay_schedules(config)
        return self._upsert_schedules(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll schedule push_all; Payroll GraphQL is read-only.')

    def _upsert_schedules(self, data, config):
        Schedule = self.env['quickbooks.payroll.pay.schedule']
        count = 0
        for schedule in data.get('payrollPaySchedules', []):
            qb_id = str(schedule.get('id') or '')
            if not qb_id:
                continue
            vals = {
                'company_id': config.company_id.id,
                'qb_pay_schedule_id': qb_id,
                'name': schedule.get('name') or qb_id,
                'frequency': schedule.get('frequency'),
                'active': bool(schedule.get('active', True)),
                'next_pay_date': schedule.get('nextPayDate') or False,
                'qb_last_synced': fields.Datetime.now(),
            }
            existing = Schedule.search([
                ('company_id', '=', config.company_id.id),
                ('qb_pay_schedule_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Schedule.create(vals)
            count += 1
        return count
