import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..compat import fire_integration_event

_logger = logging.getLogger(__name__)

ENTITY_SERVICE_MAP = {
    'customer': 'qb.sync.customers',
    'vendor': 'qb.sync.customers',
    'product': 'qb.sync.products',
    'account': 'qb.sync.accounts',
    'invoice': 'qb.sync.invoices',
    'bill': 'qb.sync.bills',
    'payment': 'qb.sync.payments',
    'bill_payment': 'qb.sync.payments',
    'journal_entry': 'qb.sync.journal.entries',
    'credit_memo': 'qb.sync.invoices',
    'estimate': 'qb.sync.invoices',
    'tax_code': 'qb.sync.tax.codes',
    'sales_receipt': 'qb.sync.sales.receipts',
    'purchase_order': 'qb.sync.purchase.orders',
    'expense': 'qb.sync.expenses',
    'employee': 'qb.sync.employees',
    'department': 'qb.sync.departments',
    'time_activity': 'qb.sync.time.activities',
    'class': 'qb.sync.classes',
    'deposit': 'qb.sync.deposits',
    'transfer': 'qb.sync.transfers',
    'term': 'qb.sync.terms',
    'attachment': 'qb.sync.attachments',
    'vendor_credit': 'qb.sync.vendor.credits',
    'refund_receipt': 'qb.sync.refund.receipts',
    'exchange_rate': 'qb.sync.exchange.rates',
    'company_info': 'qb.sync.company.info',
    'payroll_compensation': 'qb.sync.payroll',
    'timesheet': 'qb.sync.timesheets',
}

PULL_ONLY_ENTITIES = frozenset([
    'account', 'tax_code', 'term', 'attachment',
    'exchange_rate', 'company_info', 'refund_receipt',
])


class QBSyncEngine(models.AbstractModel):
    _name = 'qb.sync.engine'
    _description = 'QuickBooks Sync Engine'

    def execute_job(self, job):
        config = self.env['quickbooks.config'].get_config(
            self.env['res.company'].browse(job.company_id.id),
        )
        if config.state != 'connected':
            raise UserError('QuickBooks not connected for %s' % config.company_id.name)

        service_name = ENTITY_SERVICE_MAP.get(job.entity_type)
        if not service_name:
            raise UserError('Unknown entity type: %s' % job.entity_type)

        service = self.env[service_name]
        client = self.env['qb.api.client'].get_client(config)
        start = time.time()

        try:
            if job.direction == 'push':
                result = service.push(client, config, job)
            else:
                result = service.pull(client, config, job)

            duration_ms = int((time.time() - start) * 1000)
            qb_id = job.qb_entity_id or (result or {}).get('qb_id', '')
            self.env['quickbooks.sync.log'].log_sync(
                company_id=job.company_id.id,
                entity_type=job.entity_type,
                direction=job.direction,
                operation=job.operation,
                odoo_record_id=job.odoo_record_id,
                odoo_model=job.odoo_model,
                qb_entity_id=qb_id,
                state='success',
                duration_ms=duration_ms,
            )
            self._fire_integration_event(
                job, 'sync_completed', duration_ms,
                external_id=qb_id, odoo_model=job.odoo_model,
                odoo_record_id=job.odoo_record_id,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.env['quickbooks.sync.log'].log_sync(
                company_id=job.company_id.id,
                entity_type=job.entity_type,
                direction=job.direction,
                operation=job.operation,
                odoo_record_id=job.odoo_record_id,
                odoo_model=job.odoo_model,
                qb_entity_id=job.qb_entity_id,
                state='error',
                error_message=str(e),
                duration_ms=duration_ms,
            )
            self._fire_integration_event(
                job, 'sync_failed', duration_ms,
                status='error', error_message=str(e),
            )
            raise

    def run_full_sync(self, config):
        client = self.env['qb.api.client'].get_client(config)
        full_start = time.time()
        total_errors = 0

        entity_order = [
            'company_info', 'exchange_rate',
            'account', 'tax_code', 'term',
            'department', 'class',
            'customer', 'vendor', 'employee', 'product',
            'invoice', 'bill', 'credit_memo', 'vendor_credit',
            'sales_receipt', 'refund_receipt',
            'purchase_order', 'expense',
            'payment', 'bill_payment',
            'deposit', 'transfer',
            'journal_entry',
            'time_activity',
            'attachment',
        ]
        toggle_map = {
            'company_info': True,
            'exchange_rate': True,
            'customer': config.sync_customers,
            'vendor': config.sync_vendors,
            'product': config.sync_products,
            'invoice': config.sync_invoices,
            'bill': config.sync_bills,
            'payment': config.sync_payments,
            'bill_payment': config.sync_payments,
            'journal_entry': config.sync_journal_entries,
            'credit_memo': config.sync_credit_memos,
            'vendor_credit': getattr(config, 'sync_vendor_credits', False),
            'refund_receipt': getattr(config, 'sync_refund_receipts', False),
            'estimate': config.sync_estimates,
            'account': True,
            'tax_code': getattr(config, 'sync_tax_codes', True),
            'sales_receipt': getattr(config, 'sync_sales_receipts', False),
            'purchase_order': getattr(config, 'sync_purchase_orders', False),
            'expense': getattr(config, 'sync_expenses', False),
            'deposit': getattr(config, 'sync_deposits', False),
            'transfer': getattr(config, 'sync_transfers', False),
            'employee': getattr(config, 'sync_employees', False),
            'department': getattr(config, 'sync_departments', False),
            'time_activity': getattr(config, 'sync_time_activities', False),
            'class': getattr(config, 'sync_classes', False),
            'term': getattr(config, 'sync_terms', False),
            'attachment': getattr(config, 'sync_attachments', False),
        }

        for entity_type in entity_order:
            if not toggle_map.get(entity_type, False):
                continue
            service_name = ENTITY_SERVICE_MAP.get(entity_type)
            if not service_name:
                continue
            try:
                service = self.env[service_name]
                service.pull_all(client, config, entity_type)
                if entity_type not in PULL_ONLY_ENTITIES:
                    service.push_all(client, config, entity_type)
            except Exception:
                total_errors += 1
                _logger.exception(
                    'Full sync failed for %s in company %s',
                    entity_type, config.company_id.name,
                )

        config.write({'last_sync_date': fields.Datetime.now()})

        duration_ms = int((time.time() - full_start) * 1000)
        event_type = 'sync_completed' if total_errors == 0 else 'sync_failed'
        fire_integration_event(
            self.env, 'quickbooks', event_type,
            entity_type='full_sync',
            direction='push',
            duration_ms=duration_ms,
            records_processed=len(entity_order),
            status='success' if total_errors == 0 else 'warning',
            error_message=f'{total_errors} entity type(s) failed' if total_errors else '',
        )

    def enqueue_full_entity_sync(self, config, entity_type, direction, priority=10):
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type=entity_type,
            direction=direction,
            operation='update',
            company=config.company_id,
            priority=priority,
        )

    def _fire_integration_event(self, job, event_type, duration_ms, **kwargs):
        direction = 'push' if job.direction == 'push' else 'pull'
        fire_integration_event(
            self.env, 'quickbooks', event_type,
            entity_type=job.entity_type,
            direction=direction,
            duration_ms=duration_ms,
            records_processed=1,
            **kwargs,
        )
