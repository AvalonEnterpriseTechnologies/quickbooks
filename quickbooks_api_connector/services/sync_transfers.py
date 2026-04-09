import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTransfers(models.AbstractModel):
    _name = 'qb.sync.transfers'
    _description = 'QuickBooks Transfer Sync'

    def _qb_transfer_to_odoo(self, qb_data):
        return {
            'qb_transfer_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        debit_line = move.line_ids.filtered(lambda l: l.debit > 0)[:1]
        credit_line = move.line_ids.filtered(lambda l: l.credit > 0)[:1]

        payload = {
            'Amount': debit_line.debit if debit_line else 0,
        }
        if move.date:
            payload['TxnDate'] = move.date.isoformat()
        if debit_line and debit_line.account_id and hasattr(debit_line.account_id, 'qb_account_id'):
            if debit_line.account_id.qb_account_id:
                payload['ToAccountRef'] = {'value': debit_line.account_id.qb_account_id}
        if credit_line and credit_line.account_id and hasattr(credit_line.account_id, 'qb_account_id'):
            if credit_line.account_id.qb_account_id:
                payload['FromAccountRef'] = {'value': credit_line.account_id.qb_account_id}

        qb_id = move.qb_transfer_id
        if qb_id:
            existing = client.read('Transfer', qb_id)
            entity = existing.get('Transfer', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Transfer', payload)
        else:
            resp = client.create('Transfer', payload)

        created = resp.get('Transfer', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_transfer_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Transfer', qb_id)
        qb_data = resp.get('Transfer', {})
        if not qb_data:
            return {}
        vals = self._qb_transfer_to_odoo(qb_data)
        existing = self.env['account.move'].search(
            [('qb_transfer_id', '=', str(qb_data['Id']))], limit=1,
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
        records = client.query_all('Transfer', where_clause=where)
        Move = self.env['account.move']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_transfer_to_odoo(qb_data)
            existing = Move.search([('qb_transfer_id', '=', qb_id)], limit=1)
            if existing:
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        pass
