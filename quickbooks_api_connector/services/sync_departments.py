import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncDepartments(models.AbstractModel):
    _name = 'qb.sync.departments'
    _description = 'QuickBooks Department Sync'

    def _qb_department_to_odoo(self, qb_data):
        return {
            'name': qb_data.get('Name', 'Unknown'),
            'qb_department_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }

    def push(self, client, config, job):
        dept = self.env['hr.department'].browse(job.odoo_record_id)
        if not dept.exists():
            return {}
        payload = {'Name': dept.name}
        qb_id = dept.qb_department_id
        if qb_id:
            existing = client.read('Department', qb_id)
            entity = existing.get('Department', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Department', payload)
        else:
            resp = client.create('Department', payload)
        created = resp.get('Department', {})
        dept.write({
            'qb_department_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Department', qb_id)
        qb_data = resp.get('Department', {})
        if not qb_data:
            return {}
        vals = self._qb_department_to_odoo(qb_data)
        existing = self.env['hr.department'].search(
            [('qb_department_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            self.env['hr.department'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Department', where_clause=where)
        Dept = self.env['hr.department']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_department_to_odoo(qb_data)
            existing = Dept.search([('qb_department_id', '=', qb_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Dept.create(vals)

    def push_all(self, client, config, entity_type):
        pass
