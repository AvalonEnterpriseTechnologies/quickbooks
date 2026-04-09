import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTerms(models.AbstractModel):
    _name = 'qb.sync.terms'
    _description = 'QuickBooks Term Sync (pull only)'

    def _qb_term_to_odoo(self, qb_data):
        vals = {
            'name': qb_data.get('Name', 'Unknown'),
            'qb_term_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }
        due_days = qb_data.get('DueDays')
        if due_days:
            vals['note'] = 'Net %s days' % due_days
        return vals

    def push(self, client, config, job):
        return {}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Term', qb_id)
        qb_data = resp.get('Term', {})
        if not qb_data:
            return {}
        vals = self._qb_term_to_odoo(qb_data)
        existing = self.env['account.payment.term'].search(
            [('qb_term_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            self.env['account.payment.term'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        records = client.query_all('Term')
        Term = self.env['account.payment.term']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_term_to_odoo(qb_data)
            existing = Term.search([('qb_term_id', '=', qb_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Term.create(vals)

    def push_all(self, client, config, entity_type):
        pass
