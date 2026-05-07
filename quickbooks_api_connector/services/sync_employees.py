import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncEmployees(models.AbstractModel):
    _name = 'qb.sync.employees'
    _description = 'QuickBooks Employee Sync'

    def _check_model(self):
        if 'hr.employee' not in self.env:
            _logger.warning("hr module not installed — skipping employee sync")
            return False
        return True

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
            'qb_work_location_id': str(
                (qb_data.get('WorkLocationRef') or {}).get('value') or ''
            ),
            'qb_pay_schedule_id': str(
                (qb_data.get('PayScheduleRef') or {}).get('value') or ''
            ),
            'qb_employment_status': self._normalize_employment_status(
                qb_data.get('EmploymentStatus') or qb_data.get('Active')
            ),
            'qb_termination_date': qb_data.get('ReleasedDate') or False,
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }

        addr = qb_data.get('PrimaryAddr') or {}
        if addr.get('Line1'):
            vals['work_location_name'] = addr['Line1']

        hire_date = qb_data.get('HiredDate')
        if hire_date and 'first_contract_date' in self.env['hr.employee']._fields:
            vals['first_contract_date'] = hire_date[:10]

        return {
            key: value for key, value in vals.items()
            if key in self.env['hr.employee']._fields
        }

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
        if getattr(employee, 'qb_work_location_id', False):
            data['WorkLocationRef'] = {'value': employee.qb_work_location_id}
        if getattr(employee, 'qb_pay_schedule_id', False):
            data['PayScheduleRef'] = {'value': employee.qb_pay_schedule_id}
        if getattr(employee, 'qb_employment_status', False):
            data['EmploymentStatus'] = self._qbo_employment_status(
                employee.qb_employment_status
            )
        if getattr(employee, 'qb_termination_date', False):
            data['ReleasedDate'] = employee.qb_termination_date.isoformat()
        address = getattr(employee, 'address_id', False)
        if address:
            data['PrimaryAddr'] = {
                'Line1': address.street or '',
                'City': address.city or '',
                'CountrySubDivisionCode': address.state_id.code if address.state_id else '',
                'PostalCode': address.zip or '',
                'Country': address.country_id.code if address.country_id else '',
            }
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def _normalize_employment_status(status):
        if status is True:
            return 'active'
        if status is False:
            return 'inactive'
        status = str(status or '').lower()
        if 'term' in status or 'release' in status:
            return 'terminated'
        if 'leave' in status:
            return 'leave'
        if 'inactive' in status:
            return 'inactive'
        return 'active'

    @staticmethod
    def _qbo_employment_status(status):
        return {
            'active': 'Active',
            'terminated': 'Terminated',
            'leave': 'Leave',
            'inactive': 'Inactive',
        }.get(status or 'active', 'Active')

    def push(self, client, config, job):
        if not self._check_model():
            return {}
        employee = self.env['hr.employee'].browse(job.odoo_record_id)
        if not employee.exists():
            return {}

        payload = self._odoo_to_qb_employee(employee)
        qb_id = employee.qb_employee_id

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'employee', employee)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(employee, 'employee', entity)

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
        if not self._check_model():
            return {}
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Employee', qb_id)
        qb_data = resp.get('Employee', {})
        if not qb_data:
            return {}

        vals = self._qb_employee_to_odoo(qb_data)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('employee', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'employee', qb_data)
            existing.write(vals)
        else:
            self.env['hr.employee'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Employee', where_clause=where)
        Employee = self.env['hr.employee']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_employee_to_odoo(qb_data)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('employee', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'employee', qb_data)
                existing.write(vals)
            else:
                Employee.create(vals)

    def push_all(self, client, config, entity_type):
        if not self._check_model():
            return
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
