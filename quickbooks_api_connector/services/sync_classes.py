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
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'class', account)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(account, 'class', entity)
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
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('class', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'class', qb_data)
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
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Class', where_clause=where)
        AAA = self.env['account.analytic.account']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_class_to_odoo(qb_data)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('class', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'class', qb_data)
                existing.write(vals)
            else:
                plan = self.env['account.analytic.plan'].search([], limit=1)
                if plan:
                    vals['plan_id'] = plan.id
                AAA.create(vals)

    def push_all(self, client, config, entity_type):
        accounts = self.env['account.analytic.account'].search([
            ('qb_class_id', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for account in accounts:
            queue.enqueue(
                entity_type='class',
                direction='push',
                operation='create',
                odoo_record_id=account.id,
                odoo_model='account.analytic.account',
                company=config.company_id,
            )
