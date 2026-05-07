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

    def _odoo_term_to_qb(self, term):
        data = {'Name': term.name[:100]}
        if term.line_ids:
            line = term.line_ids[0]
            if line.days:
                data['DueDays'] = int(line.days)
        return data

    def push(self, client, config, job):
        term = self.env['account.payment.term'].browse(job.odoo_record_id)
        if not term.exists():
            return {}
        payload = self._odoo_term_to_qb(term)
        qb_id = term.qb_term_id
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'term', term)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(term, 'term', entity)
        if qb_id:
            existing = client.read('Term', qb_id)
            entity = existing.get('Term', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Term', payload)
        else:
            resp = client.create('Term', payload)
        created = resp.get('Term', {})
        term.write({
            'qb_term_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Term', qb_id)
        qb_data = resp.get('Term', {})
        if not qb_data:
            return {}
        vals = self._qb_term_to_odoo(qb_data)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('term', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'term', qb_data)
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
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('term', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'term', qb_data)
                existing.write(vals)
            else:
                Term.create(vals)

    def push_all(self, client, config, entity_type):
        terms = self.env['account.payment.term'].search([
            ('qb_term_id', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for term in terms:
            queue.enqueue(
                entity_type='term',
                direction='push',
                operation='create',
                odoo_record_id=term.id,
                odoo_model='account.payment.term',
                company=config.company_id,
            )
