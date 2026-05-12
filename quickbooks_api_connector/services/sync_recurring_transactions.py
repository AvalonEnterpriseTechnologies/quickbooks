import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncRecurringTransactions(models.AbstractModel):
    _name = 'qb.sync.recurring.transactions'
    _description = 'QuickBooks RecurringTransaction Sync'

    def pull(self, client, config, job):
        if not job.qb_entity_id:
            return {}
        response = client.read('RecurringTransaction', job.qb_entity_id)
        recurring = response.get('RecurringTransaction', {})
        if recurring:
            self._upsert_template(config, recurring)
        return {'qb_id': str(recurring.get('Id', ''))}

    def push(self, client, config, job):
        template = self.env[job.odoo_model].browse(job.odoo_record_id)
        if not template.exists():
            return {}
        payload = self._odoo_to_qbo(template)
        if template.qb_recurring_id:
            existing = client.read('RecurringTransaction', template.qb_recurring_id)
            payload['Id'] = template.qb_recurring_id
            payload['SyncToken'] = existing.get('RecurringTransaction', {}).get(
                'SyncToken', template.qb_sync_token or '0',
            )
            payload['sparse'] = True
            response = client.update('RecurringTransaction', payload)
        else:
            response = client.create('RecurringTransaction', payload)
        recurring = response.get('RecurringTransaction', {})
        if recurring:
            template.write(self._qb_to_template_vals(config, recurring))
        return {'qb_id': str(recurring.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        records = client.query_all('RecurringTransaction')
        for recurring in records:
            self._upsert_template(config, recurring)
        return {'count': len(records)}

    def push_all(self, client, config, entity_type):
        _logger.info('Recurring templates are created from native recurring documents.')
        return {'count': 0}

    def _upsert_template(self, config, recurring):
        vals = self._qb_to_template_vals(config, recurring)
        Template = self._target_model(vals['txn_type'])
        write_vals = self._native_vals(Template, vals, config)
        existing = Template.search([
            ('qb_recurring_id', '=', vals['qb_recurring_id']),
        ], limit=1)
        if existing:
            existing.with_context(skip_qb_sync=True).write(write_vals)
            return existing
        return Template.with_context(skip_qb_sync=True).create(write_vals)

    def _qb_to_template_vals(self, config, recurring):
        schedule = recurring.get('ScheduleInfo') or {}
        interval = schedule.get('IntervalInfo') or {}
        txn_type = (
            recurring.get('TxnType')
            or recurring.get('TransactionType')
            or recurring.get('TemplateType')
            or 'Invoice'
        )
        return {
            'company_id': config.company_id.id,
            'name': recurring.get('Name') or recurring.get('DocNumber') or txn_type,
            'qb_recurring_id': str(recurring.get('Id', '')),
            'qb_sync_token': str(recurring.get('SyncToken', '')),
            'txn_type': txn_type,
            'active': bool(recurring.get('Active', True)),
            'auto_post': self._auto_post(schedule.get('Type') or recurring.get('Type')),
            'auto_post_until': schedule.get('EndDate') or False,
            'invoice_date': schedule.get('NextDate') or False,
            'date': schedule.get('NextDate') or False,
            'qb_raw_json': recurring,
            'qb_last_synced': fields.Datetime.now(),
        }

    def _odoo_to_qbo(self, template):
        payload = dict(template.qb_raw_json or {})
        payload.update({
            'Name': template.name,
            'Active': getattr(template, 'active', True),
        })
        return payload

    def _target_model(self, txn_type):
        if txn_type in ('Estimate',) and 'sale.order' in self.env:
            return self.env['sale.order'].sudo()
        return self.env['account.move'].sudo()

    def _native_vals(self, Model, vals, config):
        result = {key: value for key, value in vals.items() if key in Model._fields}
        if Model._name == 'account.move':
            result.setdefault('move_type', 'entry')
            if 'journal_id' in Model._fields and not result.get('journal_id'):
                journal = self.env['qb.sync.journals'].ensure_general_journal(
                    config,
                    key='qbo:general:recurring',
                    name='QuickBooks Recurring Transactions',
                )
                result['journal_id'] = journal.id
        return result

    @staticmethod
    def _auto_post(schedule_type):
        if str(schedule_type or '').lower() in ('automated', 'scheduled'):
            return 'at_date'
        return 'no'
