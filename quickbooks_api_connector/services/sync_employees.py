import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncEmployees(models.AbstractModel):
    _name = 'qb.sync.employees'
    _description = 'QuickBooks Employee Sync'

    def _qb_employee_to_odoo(self, qb_data):
        name_parts = []
        if qb_data.get('GivenName'):
            name_parts.append(qb_data['GivenName'])
        if qb_data.get('MiddleName'):
            name_parts.append(qb_data['MiddleName'])
        if qb_data.get('FamilyName'):
            name_parts.append(qb_data['FamilyName'])
        name = ' '.join(name_parts) or qb_data.get('DisplayName', 'Unknown')

        vals = {
            'name': name,
            'work_email': (qb_data.get('PrimaryEmailAddr') or {}).get('Address', False),
            'work_phone': (qb_data.get('PrimaryPhone') or {}).get('FreeFormNumber', False),
            'mobile_phone': (qb_data.get('Mobile') or {}).get('FreeFormNumber', False),
            'qb_employee_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }

        addr = qb_data.get('PrimaryAddr') or {}
        if addr.get('Line1'):
            vals['work_location_name'] = addr['Line1']

        hire_date = qb_data.get('HiredDate')
        if hire_date:
            vals['first_contract_date'] = hire_date[:10]

        return vals

    def _odoo_to_qb_employee(self, employee):
        name_parts = (employee.name or '').split(' ', 1)
        data = {
            'GivenName': name_parts[0][:25] if name_parts else '',
            'FamilyName': name_parts[1][:25] if len(name_parts) > 1 else '',
            'DisplayName': employee.name or '',
        }
        if employee.work_email:
            data['PrimaryEmailAddr'] = {'Address': employee.work_email}
        if employee.work_phone:
            data['PrimaryPhone'] = {'FreeFormNumber': employee.work_phone}
        if employee.mobile_phone:
            data['Mobile'] = {'FreeFormNumber': employee.mobile_phone}
        return {k: v for k, v in data.items() if v is not None}

    def push(self, client, config, job):
        employee = self.env['hr.employee'].browse(job.odoo_record_id)
        if not employee.exists():
            return {}

        payload = self._odoo_to_qb_employee(employee)
        qb_id = employee.qb_employee_id

        if qb_id:
            existing = client.read('Employee', qb_id)
            entity = existing.get('Employee', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Employee', payload)
        else:
            resp = client.create('Employee', payload)

        created = resp.get('Employee', {})
        employee.write({
            'qb_employee_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Employee', qb_id)
        qb_data = resp.get('Employee', {})
        if not qb_data:
            return {}

        vals = self._qb_employee_to_odoo(qb_data)
        existing = self.env['hr.employee'].search(
            [('qb_employee_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            self.env['hr.employee'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Employee', where_clause=where)
        Employee = self.env['hr.employee']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_employee_to_odoo(qb_data)
            existing = Employee.search([('qb_employee_id', '=', qb_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Employee.create(vals)

    def push_all(self, client, config, entity_type):
        employees = self.env['hr.employee'].search([
            ('qb_employee_id', '=', False),
            ('qb_do_not_sync', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for emp in employees:
            queue.enqueue(
                entity_type='employee',
                direction='push',
                operation='create',
                odoo_record_id=emp.id,
                odoo_model='hr.employee',
                company=config.company_id,
            )
