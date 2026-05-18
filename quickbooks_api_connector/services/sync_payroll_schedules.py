import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


# Map QBO pay frequency tokens to Odoo's hr.contract.schedule_pay selection.
QBO_FREQUENCY_TO_SCHEDULE_PAY = {
    'WEEKLY': 'weekly',
    'BIWEEKLY': 'bi-weekly',
    'BI_WEEKLY': 'bi-weekly',
    'BI-WEEKLY': 'bi-weekly',
    'SEMIMONTHLY': 'semi-monthly',
    'SEMI_MONTHLY': 'semi-monthly',
    'SEMI-MONTHLY': 'semi-monthly',
    'MONTHLY': 'monthly',
    'QUARTERLY': 'quarterly',
    'ANNUALLY': 'annually',
    'YEARLY': 'annually',
    'DAILY': 'daily',
}

QBO_FREQUENCY_LABEL = {
    'weekly': 'Weekly',
    'bi-weekly': 'Bi-weekly',
    'semi-monthly': 'Semi-monthly',
    'monthly': 'Monthly',
    'quarterly': 'Quarterly',
    'annually': 'Annual',
    'daily': 'Daily',
}


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

    def _normalize_schedule_pay(self, frequency):
        token = str(frequency or '').strip().upper().replace(' ', '')
        return QBO_FREQUENCY_TO_SCHEDULE_PAY.get(token)

    def _find_or_create_structure_type(self, schedule_pay, config):
        if 'hr.payroll.structure.type' not in self.env:
            return False
        StructType = self.env['hr.payroll.structure.type'].sudo()
        label = QBO_FREQUENCY_LABEL.get(schedule_pay, schedule_pay or 'QB Payroll')
        name = 'QuickBooks - %s' % label
        domain = [('name', '=', name)]
        if 'company_id' in StructType._fields:
            domain.append(('company_id', 'in', [config.company_id.id, False]))
        existing = StructType.search(domain, limit=1)
        if existing:
            return existing
        vals = {'name': name}
        if 'country_id' in StructType._fields:
            us = self.env.ref('base.us', raise_if_not_found=False)
            if us:
                vals['country_id'] = us.id
        if 'company_id' in StructType._fields:
            vals['company_id'] = config.company_id.id
        if 'default_schedule_pay' in StructType._fields and schedule_pay:
            vals['default_schedule_pay'] = schedule_pay
        return StructType.create(vals)

    def _upsert_schedules(self, data, config):
        if 'hr.payroll.structure' not in self.env:
            _logger.warning(
                "hr_payroll module not installed - skipping pay schedule sync"
            )
            return 0
        Structure = self.env['hr.payroll.structure'].sudo()
        if 'qb_pay_schedule_id' not in Structure._fields:
            _logger.warning(
                "QuickBooks payroll bridge fields are not loaded - skipping pay "
                "schedule sync"
            )
            return 0
        count = 0
        for schedule in data.get('payrollPaySchedules', []):
            qb_id = str(schedule.get('id') or '')
            if not qb_id:
                continue
            schedule_pay = self._normalize_schedule_pay(schedule.get('frequency'))
            struct_type = self._find_or_create_structure_type(schedule_pay, config)
            vals = {
                'qb_pay_schedule_id': qb_id,
                'name': schedule.get('name') or qb_id,
                'qb_frequency': schedule.get('frequency'),
                'qb_next_pay_date': (
                    schedule.get('payDate') or schedule.get('nextPayDate') or False
                ),
                'qb_last_synced': fields.Datetime.now(),
                'qb_raw_json': schedule,
            }
            if struct_type and 'type_id' in Structure._fields:
                vals['type_id'] = struct_type.id
            if 'company_id' in Structure._fields:
                vals['company_id'] = config.company_id.id
            if 'active' in Structure._fields:
                vals['active'] = bool(schedule.get('active', True))
            vals = {k: v for k, v in vals.items() if k in Structure._fields}

            existing = Structure.search([
                ('qb_pay_schedule_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Structure.create(vals)
            count += 1
        return count
