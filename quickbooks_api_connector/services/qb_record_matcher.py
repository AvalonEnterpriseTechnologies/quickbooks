import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)


ENTITY_META = {
    'customer': {
        'model': 'res.partner',
        'qb_name': 'Customer',
        'qb_id_field': 'qb_customer_id',
        'name_field': 'name',
        'qb_display_field': 'DisplayName',
    },
    'vendor': {
        'model': 'res.partner',
        'qb_name': 'Vendor',
        'qb_id_field': 'qb_vendor_id',
        'name_field': 'name',
        'qb_display_field': 'DisplayName',
    },
    'product': {
        'model': 'product.product',
        'qb_name': 'Item',
        'qb_id_field': 'qb_item_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'invoice': {
        'model': 'account.move',
        'qb_name': 'Invoice',
        'qb_id_field': 'qb_invoice_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
        'move_type': 'out_invoice',
    },
    'estimate': {
        'model': 'sale.order',
        'qb_name': 'Estimate',
        'qb_id_field': 'qb_estimate_id',
        'name_field': 'client_order_ref',
        'qb_display_field': 'DocNumber',
    },
    'bill': {
        'model': 'account.move',
        'qb_name': 'Bill',
        'qb_id_field': 'qb_bill_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
        'move_type': 'in_invoice',
    },
    'credit_memo': {
        'model': 'account.move',
        'qb_name': 'CreditMemo',
        'qb_id_field': 'qb_creditmemo_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
        'move_type': 'out_refund',
    },
    'vendor_credit': {
        'model': 'account.move',
        'qb_name': 'VendorCredit',
        'qb_id_field': 'qb_vendorcredit_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
        'move_type': 'in_refund',
    },
    'journal_entry': {
        'model': 'account.move',
        'qb_name': 'JournalEntry',
        'qb_id_field': 'qb_je_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
        'move_type': 'entry',
    },
    'sales_receipt': {
        'model': 'account.move',
        'qb_name': 'SalesReceipt',
        'qb_id_field': 'qb_salesreceipt_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
    },
    'refund_receipt': {
        'model': 'account.move',
        'qb_name': 'RefundReceipt',
        'qb_id_field': 'qb_refundreceipt_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
    },
    'deposit': {
        'model': 'account.move',
        'qb_name': 'Deposit',
        'qb_id_field': 'qb_deposit_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
    },
    'transfer': {
        'model': 'account.move',
        'qb_name': 'Transfer',
        'qb_id_field': 'qb_transfer_id',
        'name_field': 'ref',
        'qb_display_field': 'DocNumber',
    },
    'payment': {
        'model': 'account.payment',
        'qb_name': 'Payment',
        'qb_id_field': 'qb_payment_id',
        'name_field': 'name',
        'qb_display_field': 'PaymentRefNum',
    },
    'bill_payment': {
        'model': 'account.payment',
        'qb_name': 'BillPayment',
        'qb_id_field': 'qb_billpayment_id',
        'name_field': 'name',
        'qb_display_field': 'DocNumber',
    },
    'purchase_order': {
        'model': 'purchase.order',
        'qb_name': 'PurchaseOrder',
        'qb_id_field': 'qb_po_id',
        'name_field': 'partner_ref',
        'qb_display_field': 'DocNumber',
    },
    'expense': {
        'model': 'hr.expense',
        'qb_name': 'Purchase',
        'qb_id_field': 'qb_purchase_id',
        'name_field': 'name',
        'qb_display_field': 'DocNumber',
    },
    'employee': {
        'model': 'hr.employee',
        'qb_name': 'Employee',
        'qb_id_field': 'qb_employee_id',
        'name_field': 'name',
        'qb_display_field': 'DisplayName',
    },
    'department': {
        'model': 'hr.department',
        'qb_name': 'Department',
        'qb_id_field': 'qb_department_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'class': {
        'model': 'account.analytic.account',
        'qb_name': 'Class',
        'qb_id_field': 'qb_class_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'term': {
        'model': 'account.payment.term',
        'qb_name': 'Term',
        'qb_id_field': 'qb_term_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'account': {
        'model': 'account.account',
        'qb_name': 'Account',
        'qb_id_field': 'qb_account_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'tax_code': {
        'model': 'account.tax',
        'qb_name': 'TaxCode',
        'qb_id_field': 'qb_taxcode_id',
        'name_field': 'name',
        'qb_display_field': 'Name',
    },
    'time_activity': {
        'model': 'account.analytic.line',
        'qb_name': 'TimeActivity',
        'qb_id_field': 'qb_timeactivity_id',
        'name_field': 'name',
        'qb_display_field': 'Description',
    },
}


class QBRecordMatcher(models.AbstractModel):
    _name = 'qb.record.matcher'
    _description = 'QuickBooks Record Matcher'

    @api.model
    def get_meta(self, entity_type):
        return ENTITY_META.get(entity_type, {})

    @api.model
    def find_odoo_match(self, entity_type, qb_data, company=None):
        meta = self.get_meta(entity_type)
        if not meta:
            return self.env[self._fallback_model(entity_type)].browse()

        Model = self.env[meta['model']]
        base_domain = self._company_domain(Model, company)
        qb_id = str(qb_data.get('Id') or '')
        if qb_id:
            match = Model.search(base_domain + [(meta['qb_id_field'], '=', qb_id)], limit=1)
            if match:
                return match

        match = self._find_by_natural_key(Model, meta, entity_type, qb_data, base_domain)
        if match:
            return match

        config = self.env['quickbooks.config'].search(
            [('company_id', '=', company.id)] if company else [],
            limit=1,
        )
        if config and not getattr(config, 'match_by_name', False):
            return Model.browse()
        return self._find_by_name(Model, meta, qb_data, base_domain)

    @api.model
    def find_qbo_match(self, client, entity_type, odoo_record):
        meta = self.get_meta(entity_type)
        if not meta:
            return {}
        qb_name = meta['qb_name']
        where = self._qbo_where_for_record(entity_type, odoo_record, meta)
        if not where:
            return {}
        try:
            response = client.query("SELECT * FROM %s WHERE %s" % (qb_name, where))
        except Exception:
            _logger.exception('QBO match query failed for %s record %s', entity_type, odoo_record.id)
            return {}
        records = (response.get('QueryResponse') or {}).get(qb_name) or []
        return records[0] if records else {}

    @api.model
    def link_odoo_record(self, record, entity_type, qb_data):
        meta = self.get_meta(entity_type)
        if not meta or not record:
            return
        vals = {
            meta['qb_id_field']: str(qb_data.get('Id') or ''),
            'qb_sync_token': str(qb_data.get('SyncToken') or ''),
        }
        vals = {key: value for key, value in vals.items() if key in record._fields and value}
        if vals:
            record.with_context(skip_qb_sync=True).write(vals)

    @api.model
    def read_qbo_entity(self, client, entity_type, qb_id):
        meta = self.get_meta(entity_type)
        if not meta or not qb_id:
            return {}
        response = client.read(meta['qb_name'], qb_id)
        return response.get(meta['qb_name'], {})

    def _fallback_model(self, entity_type):
        return {
            'payroll_compensation': 'quickbooks.payroll.compensation',
            'timesheet': 'account.analytic.line',
        }.get(entity_type, 'quickbooks.sync.queue')

    def _company_domain(self, Model, company):
        if company and 'company_id' in Model._fields:
            return [('company_id', 'in', [company.id, False])]
        return []

    def _find_by_natural_key(self, Model, meta, entity_type, qb_data, base_domain):
        if entity_type in ('customer', 'vendor'):
            email = ((qb_data.get('PrimaryEmailAddr') or {}).get('Address') or '').strip()
            if email and 'email' in Model._fields:
                candidates = Model.search(base_domain + [('email', 'ilike', email)], limit=5)
                return candidates.filtered(lambda rec: (rec.email or '').lower() == email.lower())[:1]

        if entity_type == 'product':
            sku = (qb_data.get('Sku') or '').strip()
            if sku and 'default_code' in Model._fields:
                return Model.search(base_domain + [('default_code', '=', sku)], limit=1)

        if meta.get('model') == 'account.move':
            return self._find_move_by_document(Model, meta, qb_data, base_domain)

        name = self._qb_display_value(meta, qb_data)
        if name and meta.get('name_field') in Model._fields:
            return Model.search(base_domain + [(meta['name_field'], '=', name)], limit=1)
        return Model.browse()

    def _find_move_by_document(self, Model, meta, qb_data, base_domain):
        doc_number = (qb_data.get('DocNumber') or '').strip()
        if not doc_number:
            return Model.browse()
        domain = base_domain + ['|', ('ref', '=', doc_number), ('name', '=', doc_number)]
        if meta.get('move_type'):
            domain.append(('move_type', '=', meta['move_type']))
        candidates = Model.search(domain, limit=10)
        txn_date = qb_data.get('TxnDate')
        total = self._amount(qb_data.get('TotalAmt') or self._line_total(qb_data))
        if txn_date:
            dated = candidates.filtered(lambda rec: str(rec.invoice_date or rec.date or '') == txn_date)
            if dated:
                candidates = dated
        if total is not None and 'amount_total' in Model._fields:
            amounted = candidates.filtered(lambda rec: abs(abs(rec.amount_total) - total) < 0.01)
            if amounted:
                candidates = amounted
        return candidates[:1]

    def _find_by_name(self, Model, meta, qb_data, base_domain):
        name = self._normalize(self._qb_display_value(meta, qb_data))
        if not name or meta.get('name_field') not in Model._fields:
            return Model.browse()
        candidates = Model.search(base_domain + [(meta['name_field'], 'ilike', self._qb_display_value(meta, qb_data))], limit=10)
        return candidates.filtered(lambda rec: self._normalize(getattr(rec, meta['name_field'], '')) == name)[:1]

    def _qbo_where_for_record(self, entity_type, record, meta):
        if entity_type in ('customer', 'vendor') and getattr(record, 'name', False):
            return "DisplayName = '%s'" % self._escape_qbo(record.name)
        if entity_type == 'product':
            if getattr(record, 'default_code', False):
                return "Sku = '%s'" % self._escape_qbo(record.default_code)
            return "Name = '%s'" % self._escape_qbo(record.name)
        if meta.get('model') == 'account.move':
            doc_number = record.ref or record.name
            if doc_number and doc_number != '/':
                return "DocNumber = '%s'" % self._escape_qbo(doc_number)
        name_field = meta.get('name_field')
        if name_field and name_field in record._fields and getattr(record, name_field, False):
            return "%s = '%s'" % (
                meta['qb_display_field'],
                self._escape_qbo(getattr(record, name_field)),
            )
        return ''

    def _qb_display_value(self, meta, qb_data):
        return (qb_data.get(meta.get('qb_display_field')) or '').strip()

    @staticmethod
    def _escape_qbo(value):
        return str(value or '').replace('\\', '\\\\').replace("'", "\\'")

    @staticmethod
    def _normalize(value):
        return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()

    @staticmethod
    def _amount(value):
        try:
            return abs(float(value))
        except (TypeError, ValueError):
            return None

    def _line_total(self, qb_data):
        return sum(self._amount(line.get('Amount')) or 0.0 for line in qb_data.get('Line', []))
