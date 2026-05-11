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
        template = self.env['quickbooks.recurring.template'].browse(job.odoo_record_id)
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
        templates = self.env['quickbooks.recurring.template'].search([
            ('company_id', '=', config.company_id.id),
            ('qb_recurring_id', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for template in templates:
            queue.enqueue(
                entity_type='recurring_transaction',
                direction='push',
                operation='create',
                odoo_record_id=template.id,
                odoo_model='quickbooks.recurring.template',
                company=config.company_id,
            )
        return {'count': len(templates)}

    def _upsert_template(self, config, recurring):
        vals = self._qb_to_template_vals(config, recurring)
        Template = self.env['quickbooks.recurring.template'].sudo()
        existing = Template.search([
            ('company_id', '=', config.company_id.id),
            ('qb_recurring_id', '=', vals['qb_recurring_id']),
        ], limit=1)
        if existing:
            existing.with_context(skip_qb_sync=True).write(vals)
            return existing
        return Template.with_context(skip_qb_sync=True).create(vals)

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
            'schedule_type': schedule.get('Type') or recurring.get('Type') or '',
            'interval_type': interval.get('Type') or '',
            'next_date': schedule.get('NextDate') or False,
            'previous_date': schedule.get('PreviousDate') or False,
            'raw_json': recurring,
            'qb_last_synced': fields.Datetime.now(),
        }

    def _odoo_to_qbo(self, template):
        payload = dict(template.raw_json or {})
        payload.update({
            'Name': template.name,
            'TxnType': template.txn_type,
            'Active': template.active,
        })
        if template.schedule_type or template.interval_type or template.next_date:
            schedule = dict(payload.get('ScheduleInfo') or {})
            if template.schedule_type:
                schedule['Type'] = template.schedule_type
            if template.next_date:
                schedule['NextDate'] = fields.Date.to_string(template.next_date)
            if template.interval_type:
                interval = dict(schedule.get('IntervalInfo') or {})
                interval['Type'] = template.interval_type
                schedule['IntervalInfo'] = interval
            payload['ScheduleInfo'] = schedule
        return payload
