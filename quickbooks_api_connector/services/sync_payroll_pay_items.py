import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayrollPayItems(models.AbstractModel):
    _name = 'qb.sync.payroll.pay.items'
    _description = 'QuickBooks Payroll Pay Item Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll pay item push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_pay_items_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        data = self.env['qb.payroll.client'].fetch_pay_items(config)
        return self._upsert_pay_items(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll pay item push_all; Payroll GraphQL is read-only.')

    def _upsert_pay_items(self, data, config):
        PayItem = self.env['quickbooks.payroll.pay.item']
        count = 0
        for item in data.get('payrollPayItems', []):
            qb_id = str(item.get('id') or '')
            if not qb_id:
                continue
            vals = {
                'company_id': config.company_id.id,
                'qb_pay_item_id': qb_id,
                'name': item.get('name') or qb_id,
                'pay_item_type': item.get('type'),
                'active': bool(item.get('active', True)),
                'qb_last_synced': fields.Datetime.now(),
            }
            existing = PayItem.search([
                ('company_id', '=', config.company_id.id),
                ('qb_pay_item_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                PayItem.create(vals)
            count += 1
        return count
