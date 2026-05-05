import logging

from odoo import api, models

from .qb_record_matcher import ENTITY_META

_logger = logging.getLogger(__name__)


class QBReconciliation(models.AbstractModel):
    _name = 'qb.reconciliation'
    _description = 'QuickBooks Two-way Reconciliation'

    @api.model
    def run_for_all_companies(self):
        configs = self.env['quickbooks.config'].search([('state', '=', 'connected')])
        for config in configs:
            try:
                self.run(config)
            except Exception:
                _logger.exception('QBO reconciliation failed for %s', config.company_id.name)

    @api.model
    def run(self, config, entity_types=None):
        client = self.env['qb.api.client'].get_client(config)
        entity_types = entity_types or self._enabled_entity_types(config)
        results = {}
        for entity_type in entity_types:
            meta = ENTITY_META.get(entity_type)
            if not meta or entity_type in ('attachment', 'payroll_compensation', 'timesheet'):
                continue
            try:
                results[entity_type] = self._reconcile_entity(client, config, entity_type, meta)
            except Exception as exc:
                self._log(
                    config, entity_type, 'warning',
                    'Reconciliation failed: %s' % exc,
                )
                _logger.exception('Reconciliation failed for %s', entity_type)
        return results

    def _enabled_entity_types(self, config):
        toggle_map = {
            'customer': 'sync_customers',
            'vendor': 'sync_vendors',
            'product': 'sync_products',
            'invoice': 'sync_invoices',
            'bill': 'sync_bills',
            'payment': 'sync_payments',
            'bill_payment': 'sync_payments',
            'journal_entry': 'sync_journal_entries',
            'credit_memo': 'sync_credit_memos',
            'estimate': 'sync_estimates',
            'tax_code': 'sync_tax_codes',
            'sales_receipt': 'sync_sales_receipts',
            'purchase_order': 'sync_purchase_orders',
            'expense': 'sync_expenses',
            'deposit': 'sync_deposits',
            'transfer': 'sync_transfers',
            'employee': 'sync_employees',
            'department': 'sync_departments',
            'time_activity': 'sync_time_activities',
            'class': 'sync_classes',
            'term': 'sync_terms',
            'vendor_credit': 'sync_vendor_credits',
            'refund_receipt': 'sync_refund_receipts',
            'account': None,
        }
        return [
            entity_type for entity_type, toggle in toggle_map.items()
            if toggle is None or getattr(config, toggle, False)
        ]

    def _reconcile_entity(self, client, config, entity_type, meta):
        records = client.query_all(meta['qb_name'])
        qbo_by_id = {str(record.get('Id')): record for record in records if record.get('Id')}
        Model = self.env[meta['model']]
        local = Model.search(self._local_domain(Model, meta, config))
        local_by_qb_id = {
            str(getattr(record, meta['qb_id_field'])): record
            for record in local
            if getattr(record, meta['qb_id_field'], False)
        }

        buckets = {'qbo_only': [], 'odoo_only': [], 'linked_drift': []}
        matcher = self.env['qb.record.matcher']

        for qb_id, qb_data in qbo_by_id.items():
            record = local_by_qb_id.get(qb_id)
            if not record:
                record = matcher.find_odoo_match(entity_type, qb_data, config.company_id)
                if record:
                    matcher.link_odoo_record(record, entity_type, qb_data)
                    self._log(
                        config, entity_type, 'warning',
                        'Auto-linked Odoo %s %s to QBO %s during reconciliation.'
                        % (record._name, record.id, qb_id),
                        record=record, qb_id=qb_id,
                    )
                else:
                    buckets['qbo_only'].append(qb_id)
                    self._enqueue(config, entity_type, 'pull', 'update', qb_id=qb_id)
                continue
            if self._has_drift(record, qb_data, meta):
                buckets['linked_drift'].append(qb_id)
                self._enqueue_for_conflict_strategy(config, entity_type, record, qb_id)

        missing_in_qbo = set(local_by_qb_id) - set(qbo_by_id)
        for qb_id in missing_in_qbo:
            record = local_by_qb_id[qb_id]
            buckets['odoo_only'].append(record.id)
            self._enqueue(config, entity_type, 'push', 'update', record=record)

        for bucket, values in buckets.items():
            if values:
                self._log(
                    config, entity_type, 'warning',
                    'Reconciliation %s: %s' % (bucket, ', '.join(map(str, values[:50]))),
                )
        return buckets

    def _local_domain(self, Model, meta, config):
        domain = [(meta['qb_id_field'], '!=', False)]
        if 'company_id' in Model._fields:
            domain.append(('company_id', '=', config.company_id.id))
        if meta.get('move_type') and 'move_type' in Model._fields:
            domain.append(('move_type', '=', meta['move_type']))
        if 'qb_do_not_sync' in Model._fields:
            domain.append(('qb_do_not_sync', '=', False))
        return domain

    def _has_drift(self, record, qb_data, meta):
        if 'qb_sync_token' in record._fields and qb_data.get('SyncToken'):
            if record.qb_sync_token and record.qb_sync_token != str(qb_data.get('SyncToken')):
                return True
        qb_name = qb_data.get(meta.get('qb_display_field'))
        if not qb_name:
            return False
        local_name = ''
        if record._name in ('res.partner', 'product.product'):
            local_name = record.name
        elif record._name == 'account.move':
            local_name = record.ref or record.name
        elif meta.get('name_field') in record._fields:
            local_name = getattr(record, meta['name_field'])
        return bool(local_name and qb_name and local_name != qb_name)

    def _enqueue_for_conflict_strategy(self, config, entity_type, record, qb_id):
        if config.conflict_resolution == 'qbo_wins':
            self._enqueue(config, entity_type, 'pull', 'update', qb_id=qb_id)
        else:
            self._enqueue(config, entity_type, 'push', 'update', record=record, qb_id=qb_id)

    def _enqueue(self, config, entity_type, direction, operation, record=None, qb_id=None):
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type=entity_type,
            direction=direction,
            operation=operation,
            odoo_record_id=record.id if record else None,
            odoo_model=record._name if record else None,
            qb_entity_id=qb_id,
            company=config.company_id,
            idempotency_key='reconcile_%s_%s_%s_%s_%s' % (
                config.realm_id,
                entity_type,
                direction,
                qb_id or '',
                record.id if record else '',
            ),
        )

    def _log(self, config, entity_type, state, message, record=None, qb_id=None):
        self.env['quickbooks.sync.log'].log_sync(
            company_id=config.company_id.id,
            entity_type=entity_type,
            direction='pull',
            operation='read',
            odoo_record_id=record.id if record else None,
            odoo_model=record._name if record else None,
            qb_entity_id=qb_id,
            state=state,
            error_message=message,
        )
