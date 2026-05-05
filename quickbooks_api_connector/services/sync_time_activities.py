import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTimeActivities(models.AbstractModel):
    _name = 'qb.sync.time.activities'
    _description = 'QuickBooks TimeActivity Sync'

    def _qb_timeactivity_to_odoo(self, qb_data):
        hours = int(qb_data.get('Hours', 0))
        minutes = int(qb_data.get('Minutes', 0))
        unit_amount = hours + minutes / 60.0

        vals = {
            'name': qb_data.get('Description', 'QB TimeActivity %s' % qb_data.get('Id', '')),
            'unit_amount': unit_amount,
            'date': qb_data.get('TxnDate', False),
            'qb_timeactivity_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }

        emp_ref = qb_data.get('EmployeeRef')
        if emp_ref and 'hr.employee' in self.env:
            employee = self.env['hr.employee'].search(
                [('qb_employee_id', '=', emp_ref.get('value'))], limit=1,
            )
            if employee:
                vals['employee_id'] = employee.id
                if employee.user_id:
                    vals['user_id'] = employee.user_id.id

        return vals

    def _odoo_to_qb_timeactivity(self, line):
        hours = int(line.unit_amount)
        minutes = int(round((line.unit_amount - hours) * 60))
        data = {
            'TxnDate': line.date.isoformat() if line.date else None,
            'NameOf': 'Employee',
            'Hours': hours,
            'Minutes': minutes,
            'Description': line.name or '',
        }
        if hasattr(line, 'employee_id') and line.employee_id:
            if line.employee_id.qb_employee_id:
                data['EmployeeRef'] = {'value': line.employee_id.qb_employee_id}
        return {k: v for k, v in data.items() if v is not None}

    def push(self, client, config, job):
        line = self.env['account.analytic.line'].browse(job.odoo_record_id)
        if not line.exists():
            return {}

        payload = self._odoo_to_qb_timeactivity(line)
        qb_id = line.qb_timeactivity_id

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'time_activity', line)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(line, 'time_activity', entity)

        if qb_id:
            existing = client.read('TimeActivity', qb_id)
            entity = existing.get('TimeActivity', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('TimeActivity', payload)
        else:
            resp = client.create('TimeActivity', payload)

        created = resp.get('TimeActivity', {})
        line.write({
            'qb_timeactivity_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('TimeActivity', qb_id)
        qb_data = resp.get('TimeActivity', {})
        if not qb_data:
            return {}
        vals = self._qb_timeactivity_to_odoo(qb_data)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('time_activity', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'time_activity', qb_data)
            existing.write(vals)
        else:
            self.env['account.analytic.line'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('TimeActivity', where_clause=where)
        AAL = self.env['account.analytic.line']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_timeactivity_to_odoo(qb_data)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('time_activity', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'time_activity', qb_data)
                existing.write(vals)
            else:
                AAL.create(vals)

    def push_all(self, client, config, entity_type):
        lines = self.env['account.analytic.line'].search([
            ('qb_timeactivity_id', '=', False),
            ('unit_amount', '>', 0),
        ])
        queue = self.env['quickbooks.sync.queue']
        for line in lines:
            queue.enqueue(
                entity_type='time_activity',
                direction='push',
                operation='create',
                odoo_record_id=line.id,
                odoo_model='account.analytic.line',
                company=config.company_id,
            )
