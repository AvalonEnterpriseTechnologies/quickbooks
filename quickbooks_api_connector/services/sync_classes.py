import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncClasses(models.AbstractModel):
    _name = 'qb.sync.classes'
    _description = 'QuickBooks Class Sync'

    def _qb_class_to_odoo(self, qb_data):
        return {
            'name': qb_data.get('Name', 'Unknown'),
            'qb_class_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }

    def push(self, client, config, job):
        account = self.env['account.analytic.account'].browse(job.odoo_record_id)
        if not account.exists():
            return {}
        payload = {'Name': account.name}
        qb_id = account.qb_class_id
        if qb_id:
            existing = client.read('Class', qb_id)
            entity = existing.get('Class', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Class', payload)
        else:
            resp = client.create('Class', payload)
        created = resp.get('Class', {})
        account.write({
            'qb_class_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Class', qb_id)
        qb_data = resp.get('Class', {})
        if not qb_data:
            return {}
        vals = self._qb_class_to_odoo(qb_data)
        existing = self.env['account.analytic.account'].search(
            [('qb_class_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            plan = self.env['account.analytic.plan'].search([], limit=1)
            if plan:
                vals['plan_id'] = plan.id
            self.env['account.analytic.account'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Class', where_clause=where)
        AAA = self.env['account.analytic.account']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_class_to_odoo(qb_data)
            existing = AAA.search([('qb_class_id', '=', qb_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                plan = self.env['account.analytic.plan'].search([], limit=1)
                if plan:
                    vals['plan_id'] = plan.id
                AAA.create(vals)

    def push_all(self, client, config, entity_type):
        pass
