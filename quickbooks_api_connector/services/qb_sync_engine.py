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
    'estimate': 'qb.sync.estimates',
    'tax_code': 'qb.sync.tax.codes',
    'sales_receipt': 'qb.sync.sales.receipts',
    'purchase_order': 'qb.sync.purchase.orders',
    'expense': 'qb.sync.expenses',
    'employee': 'qb.sync.employees',
    'department': 'qb.sync.departments',
    'time_activity': 'qb.sync.time.activities',
    'project': 'qb.sync.projects',
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
    'payroll_employee': 'qb.sync.payroll.employees',
    'payroll_pay_item': 'qb.sync.payroll.pay.items',
    'payroll_schedule': 'qb.sync.payroll.schedules',
    'payroll_check': 'qb.sync.payroll.checks',
    'work_location': 'qb.sync.work.locations',
    'inventory_adjustment': 'qb.sync.inventory.adjustments',
    'timesheet': 'qb.sync.timesheets',
}

PULL_ONLY_ENTITIES = frozenset([
    'account', 'tax_code', 'term', 'attachment',
    'exchange_rate', 'company_info',
])

CDC_QBO_TO_ENTITY = {
    'Account': 'account',
    'Bill': 'bill',
    'BillPayment': 'bill_payment',
    'Class': 'class',
    'CreditMemo': 'credit_memo',
    'Customer': 'customer',
    'Department': 'department',
    'Deposit': 'deposit',
    'Employee': 'employee',
    'Estimate': 'estimate',
    'Invoice': 'invoice',
    'Item': 'product',
    'JournalEntry': 'journal_entry',
    'Payment': 'payment',
    'Purchase': 'expense',
    'PurchaseOrder': 'purchase_order',
    'RefundReceipt': 'refund_receipt',
    'SalesReceipt': 'sales_receipt',
    'TaxCode': 'tax_code',
    'Term': 'term',
    'TimeActivity': 'time_activity',
    'Transfer': 'transfer',
    'Vendor': 'vendor',
    'VendorCredit': 'vendor_credit',
    'Project': 'project',
}


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
                if getattr(config, 'verify_after_push', True):
                    self._verify_push_readback(client, config, job, result or {})
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
            'customer', 'vendor', 'employee', 'project', 'product',
            'invoice', 'bill', 'credit_memo', 'estimate', 'vendor_credit',
            'sales_receipt', 'refund_receipt',
            'purchase_order', 'expense',
            'payment', 'bill_payment',
            'deposit', 'transfer',
            'journal_entry',
            'time_activity',
            'payroll_employee', 'payroll_compensation', 'payroll_pay_item',
            'payroll_schedule', 'payroll_check', 'work_location', 'timesheet',
            'inventory_adjustment',
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
            'project': getattr(config, 'sync_projects', False),
            'payroll_compensation': getattr(config, 'payroll_enabled', False),
            'payroll_employee': getattr(config, 'payroll_enabled', False),
            'payroll_pay_item': getattr(config, 'payroll_enabled', False),
            'payroll_schedule': getattr(config, 'payroll_enabled', False),
            'payroll_check': getattr(config, 'payroll_enabled', False),
            'work_location': getattr(config, 'payroll_enabled', False),
            'timesheet': getattr(config, 'qbt_enabled', False),
            'inventory_adjustment': getattr(config, 'sync_inventory_adjustments', False),
            'class': getattr(config, 'sync_classes', False),
            'term': getattr(config, 'sync_terms', False),
            'attachment': getattr(config, 'sync_attachments', False),
        }
        cdc_records = self._collect_cdc_records(client, config, entity_order)

        for entity_type in entity_order:
            if not toggle_map.get(entity_type, False):
                continue
            service_name = ENTITY_SERVICE_MAP.get(entity_type)
            if not service_name:
                continue
            try:
                service = self.env[service_name]
                if entity_type in cdc_records:
                    self._enqueue_cdc_records(config, entity_type, cdc_records[entity_type])
                else:
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

    def _collect_cdc_records(self, client, config, entity_order):
        if not config.last_sync_date:
            return {}
        qbo_names = [
            qbo_name for qbo_name, entity_type in CDC_QBO_TO_ENTITY.items()
            if entity_type in entity_order
        ]
        try:
            changed_since = self.env['qb.api.client'].format_qbo_datetime(
                config.last_sync_date,
            )
            return {
                CDC_QBO_TO_ENTITY[qbo_name]: records
                for qbo_name, records in client.cdc(
                    ','.join(qbo_names), changed_since,
                ).items()
                if qbo_name in CDC_QBO_TO_ENTITY
            }
        except Exception:
            _logger.exception(
                'CDC incremental sync failed for company %s; falling back to query sync',
                config.company_id.name,
            )
            return {}

    def _enqueue_cdc_records(self, config, entity_type, records):
        queue = self.env['quickbooks.sync.queue']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            if not qb_id:
                continue
            queue.enqueue(
                entity_type=entity_type,
                direction='pull',
                operation='update',
                qb_entity_id=qb_id,
                company=config.company_id,
                idempotency_key='cdc_%s_%s_%s' % (
                    config.realm_id, entity_type, qb_id,
                ),
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

    def _verify_push_readback(self, client, config, job, result):
        qb_id = result.get('qb_id') or job.qb_entity_id
        if not qb_id:
            return
        matcher = self.env['qb.record.matcher']
        qb_data = matcher.read_qbo_entity(client, job.entity_type, qb_id)
        if not qb_data:
            self.env['quickbooks.sync.log'].log_sync(
                company_id=job.company_id.id,
                entity_type=job.entity_type,
                direction='push',
                operation='read',
                odoo_record_id=job.odoo_record_id,
                odoo_model=job.odoo_model,
                qb_entity_id=qb_id,
                state='warning',
                error_message='Post-push read-back could not find the QBO record.',
            )
            self.env['quickbooks.sync.queue'].enqueue(
                entity_type=job.entity_type,
                direction='pull',
                operation='update',
                qb_entity_id=qb_id,
                company=config.company_id,
                idempotency_key='verify_pull_%s_%s_%s' % (
                    config.realm_id, job.entity_type, qb_id,
                ),
            )
            return

        drift = self._push_readback_drift(job, qb_data)
        if drift:
            self.env['quickbooks.sync.log'].log_sync(
                company_id=job.company_id.id,
                entity_type=job.entity_type,
                direction='push',
                operation='read',
                odoo_record_id=job.odoo_record_id,
                odoo_model=job.odoo_model,
                qb_entity_id=qb_id,
                state='warning',
                error_message='Post-push read-back drift: %s' % '; '.join(drift),
            )

    def _push_readback_drift(self, job, qb_data):
        if not job.odoo_model or not job.odoo_record_id:
            return []
        record = self.env[job.odoo_model].browse(job.odoo_record_id)
        if not record.exists():
            return []
        drift = []
        qb_token = str(qb_data.get('SyncToken') or '')
        if qb_token and 'qb_sync_token' in record._fields and record.qb_sync_token != qb_token:
            drift.append('SyncToken Odoo=%s QBO=%s' % (record.qb_sync_token, qb_token))
        meta = self.env['qb.record.matcher'].get_meta(job.entity_type)
        qb_name = qb_data.get(meta.get('qb_display_field')) if meta else None
        odoo_name = ''
        if job.odoo_model == 'res.partner':
            odoo_name = record.name
        elif job.odoo_model == 'product.product':
            odoo_name = record.name
        elif job.odoo_model == 'account.move':
            odoo_name = record.ref or record.name
        if qb_name and odoo_name and qb_name != odoo_name:
            drift.append('Name Odoo=%s QBO=%s' % (odoo_name, qb_name))
        return drift
