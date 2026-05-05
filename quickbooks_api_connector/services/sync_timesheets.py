import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTimesheets(models.AbstractModel):
    _name = 'qb.sync.timesheets'
    _description = 'QuickBooks Time (TSheets) Timesheet Sync'

    def _qbt_timesheet_to_odoo(self, ts_data):
        duration_seconds = ts_data.get('duration', 0)
        unit_amount = duration_seconds / 3600.0

        vals = {
            'name': ts_data.get('notes', 'QBT Timesheet %s' % ts_data.get('id', '')),
            'unit_amount': unit_amount,
            'date': ts_data.get('date', False),
            'qb_timesheet_id': str(ts_data.get('id', '')),
            'qb_last_synced': fields.Datetime.now(),
        }

        user_id = ts_data.get('user_id')
        if user_id and 'hr.employee' in self.env:
            employee = self.env['hr.employee'].search(
                [('qb_employee_id', '=', str(user_id))], limit=1,
            )
            if employee:
                vals['employee_id'] = employee.id
                if employee.user_id:
                    vals['user_id'] = employee.user_id.id

        return vals

    def _odoo_timesheet_to_qbt(self, line):
        payload = {
            'date': line.date.isoformat() if line.date else False,
            'duration': int(round((line.unit_amount or 0.0) * 3600)),
            'notes': line.name or '',
        }
        employee = getattr(line, 'employee_id', False)
        if employee and employee.qb_employee_id:
            payload['user_id'] = int(employee.qb_employee_id)
        jobcode = getattr(line, 'account_id', False)
        if jobcode and getattr(jobcode, 'qb_class_id', False):
            payload['jobcode_id'] = int(jobcode.qb_class_id)
        return {key: value for key, value in payload.items() if value not in (False, None)}

    def push(self, client, config, job):
        if not getattr(config, 'qbt_enabled', False):
            return {}
        line = self.env['account.analytic.line'].browse(job.odoo_record_id)
        if not line.exists():
            return {}

        qbt_client = self.env['qbt.api.client'].get_client(config)
        payload = self._odoo_timesheet_to_qbt(line)
        if line.qb_timesheet_id:
            resp = qbt_client.post(
                'timesheets/%s' % line.qb_timesheet_id,
                {'data': payload},
            )
            ts_id = line.qb_timesheet_id
        else:
            resp = qbt_client.post('timesheets', {'data': [payload]})
            results = resp.get('results', {}).get('timesheets', {})
            ts_id = next(iter(results.keys()), '')
        line.write({
            'qb_timesheet_id': str(ts_id),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(ts_id)}

    def pull(self, client, config, job):
        if not getattr(config, 'qbt_enabled', False):
            return {}
        qbt_client = self.env['qbt.api.client'].get_client(config)
        ts_id = job.qb_entity_id
        if not ts_id:
            return {}

        resp = qbt_client.get('timesheets', params={'ids': ts_id})
        timesheets = (resp.get('results', {}).get('timesheets', {}) or {})
        ts_data = timesheets.get(str(ts_id))
        if not ts_data:
            return {}

        vals = self._qbt_timesheet_to_odoo(ts_data)
        AAL = self.env['account.analytic.line']
        existing = AAL.search([('qb_timesheet_id', '=', str(ts_id))], limit=1)
        if existing:
            existing.write(vals)
        else:
            AAL.create(vals)
        return {'qb_id': str(ts_id)}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'qbt_enabled', False):
            return
        qbt_client = self.env['qbt.api.client'].get_client(config)
        page = 1
        AAL = self.env['account.analytic.line']

        while True:
            resp = qbt_client.get_timesheets(page=page)
            timesheets = resp.get('results', {}).get('timesheets', {})
            if not timesheets:
                break
            for ts_id, ts_data in timesheets.items():
                vals = self._qbt_timesheet_to_odoo(ts_data)
                existing = AAL.search(
                    [('qb_timesheet_id', '=', str(ts_id))], limit=1,
                )
                if existing:
                    existing.write(vals)
                else:
                    AAL.create(vals)
            if not resp.get('more', False):
                break
            page += 1

    def push_all(self, client, config, entity_type):
        if not getattr(config, 'qbt_enabled', False):
            return
        lines = self.env['account.analytic.line'].search([
            ('qb_timesheet_id', '=', False),
            ('unit_amount', '>', 0),
        ])
        queue = self.env['quickbooks.sync.queue']
        for line in lines:
            queue.enqueue(
                entity_type='timesheet',
                direction='push',
                operation='create',
                odoo_record_id=line.id,
                odoo_model='account.analytic.line',
                company=config.company_id,
            )
