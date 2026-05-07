import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncExpenses(models.AbstractModel):
    _name = 'qb.sync.expenses'
    _description = 'QuickBooks Purchase/Expense Sync'

    def _check_model(self):
        if 'hr.expense' not in self.env:
            _logger.warning("hr_expense module not installed — skipping expense sync")
            return False
        return True

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
        if not self._check_model():
            return {}
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
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'expense', expense)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(expense, 'expense', entity)
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
        if not self._check_model():
            return {}
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Purchase', qb_id)
        qb_data = resp.get('Purchase', {})
        if not qb_data:
            return {}

        vals = self._qb_purchase_to_odoo(qb_data)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('expense', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'expense', qb_data)
            existing.with_context(skip_qb_sync=True).write(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Purchase', where_clause=where)
        Expense = self.env['hr.expense']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_purchase_to_odoo(qb_data)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('expense', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'expense', qb_data)
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        if not self._check_model():
            return
        expenses = self.env['hr.expense'].search([
            ('qb_purchase_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for expense in expenses:
            queue.enqueue(
                entity_type='expense',
                direction='push',
                operation='create',
                odoo_record_id=expense.id,
                odoo_model='hr.expense',
                company=config.company_id,
            )
