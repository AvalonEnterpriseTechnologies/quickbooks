import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncExpenses(models.AbstractModel):
    _name = 'qb.sync.expenses'
    _description = 'QuickBooks Purchase/Expense Sync'

    def _qb_purchase_to_odoo(self, qb_data):
        vals = {
            'qb_purchase_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'name': 'QB Purchase %s' % qb_data.get('Id', ''),
            'total_amount': abs(float(qb_data.get('TotalAmt', 0))),
            'date': qb_data.get('TxnDate', False),
        }
        return vals

    def push(self, client, config, job):
        expense = self.env['hr.expense'].browse(job.odoo_record_id)
        if not expense.exists():
            return {}

        lines = [{
            'DetailType': 'AccountBasedExpenseLineDetail',
            'Amount': expense.total_amount,
            'AccountBasedExpenseLineDetail': {},
            'Description': expense.name or '',
        }]
        payload = {
            'PaymentType': 'Cash',
            'Line': lines,
            'TxnDate': expense.date.isoformat() if expense.date else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        qb_id = expense.qb_purchase_id
        if qb_id:
            existing = client.read('Purchase', qb_id)
            entity = existing.get('Purchase', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Purchase', payload)
        else:
            resp = client.create('Purchase', payload)

        created = resp.get('Purchase', {})
        expense.with_context(skip_qb_sync=True).write({
            'qb_purchase_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Purchase', qb_id)
        qb_data = resp.get('Purchase', {})
        if not qb_data:
            return {}

        vals = self._qb_purchase_to_odoo(qb_data)
        existing = self.env['hr.expense'].search(
            [('qb_purchase_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.with_context(skip_qb_sync=True).write(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Purchase', where_clause=where)
        Expense = self.env['hr.expense']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_purchase_to_odoo(qb_data)
            existing = Expense.search([('qb_purchase_id', '=', qb_id)], limit=1)
            if existing:
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        pass
