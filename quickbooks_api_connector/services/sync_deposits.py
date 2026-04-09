import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncDeposits(models.AbstractModel):
    _name = 'qb.sync.deposits'
    _description = 'QuickBooks Deposit Sync'

    def _qb_deposit_to_odoo(self, qb_data):
        return {
            'qb_deposit_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        lines = []
        for line in move.line_ids.filtered(lambda l: l.debit > 0):
            detail = {
                'DetailType': 'DepositLineDetail',
                'Amount': line.debit,
                'DepositLineDetail': {},
            }
            if line.account_id and hasattr(line.account_id, 'qb_account_id') and line.account_id.qb_account_id:
                detail['DepositLineDetail']['AccountRef'] = {
                    'value': line.account_id.qb_account_id,
                }
            lines.append(detail)

        payload = {'Line': lines}
        if move.date:
            payload['TxnDate'] = move.date.isoformat()

        qb_id = move.qb_deposit_id
        if qb_id:
            existing = client.read('Deposit', qb_id)
            entity = existing.get('Deposit', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Deposit', payload)
        else:
            resp = client.create('Deposit', payload)

        created = resp.get('Deposit', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_deposit_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Deposit', qb_id)
        qb_data = resp.get('Deposit', {})
        if not qb_data:
            return {}
        vals = self._qb_deposit_to_odoo(qb_data)
        existing = self.env['account.move'].search(
            [('qb_deposit_id', '=', str(qb_data['Id']))], limit=1,
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
        records = client.query_all('Deposit', where_clause=where)
        Move = self.env['account.move']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_deposit_to_odoo(qb_data)
            existing = Move.search([('qb_deposit_id', '=', qb_id)], limit=1)
            if existing:
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        pass
