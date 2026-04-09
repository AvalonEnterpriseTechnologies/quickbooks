import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QuickbooksSyncLog(models.Model):
    _name = 'quickbooks.sync.log'
    _description = 'QuickBooks Sync Log'
    _order = 'create_date desc'
    _rec_name = 'summary'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    entity_type = fields.Selection(
        [('customer', 'Customer'),
         ('vendor', 'Vendor'),
         ('product', 'Product'),
         ('account', 'Account'),
         ('invoice', 'Invoice'),
         ('bill', 'Bill'),
         ('payment', 'Payment'),
         ('bill_payment', 'Bill Payment'),
         ('journal_entry', 'Journal Entry'),
         ('credit_memo', 'Credit Memo'),
         ('estimate', 'Estimate'),
         ('tax_code', 'Tax Code'),
         ('sales_receipt', 'Sales Receipt'),
         ('refund_receipt', 'Refund Receipt'),
         ('purchase_order', 'Purchase Order'),
         ('expense', 'Expense / Purchase'),
         ('deposit', 'Deposit'),
         ('transfer', 'Transfer'),
         ('employee', 'Employee'),
         ('department', 'Department'),
         ('time_activity', 'Time Activity'),
         ('class', 'Class'),
         ('term', 'Payment Term'),
         ('attachment', 'Attachment'),
         ('vendor_credit', 'Vendor Credit'),
         ('refund_receipt', 'Refund Receipt'),
         ('exchange_rate', 'Exchange Rate'),
         ('company_info', 'Company Info'),
         ('payroll_compensation', 'Payroll Compensation'),
         ('timesheet', 'Timesheet (QBT)'),
         ('full_sync', 'Full Sync')],
        required=True,
    )
    direction = fields.Selection(
        [('push', 'Odoo → QBO'), ('pull', 'QBO → Odoo')],
        required=True,
    )
    operation = fields.Selection(
        [('create', 'Create'), ('update', 'Update'),
         ('delete', 'Delete'), ('read', 'Read')],
        required=True,
    )
    odoo_record_id = fields.Integer(string='Odoo Record ID')
    odoo_model = fields.Char(string='Odoo Model')
    qb_entity_id = fields.Char(string='QB Entity ID')
    state = fields.Selection(
        [('success', 'Success'), ('error', 'Error'), ('warning', 'Warning')],
        required=True, default='success',
    )
    summary = fields.Char(string='Summary', compute='_compute_summary', store=True)
    error_message = fields.Text(string='Error Message')
    request_data = fields.Text(string='Request Data')
    response_data = fields.Text(string='Response Data')
    duration_ms = fields.Integer(string='Duration (ms)')

    @api.depends('entity_type', 'direction', 'operation', 'state')
    def _compute_summary(self):
        for rec in self:
            rec.summary = '%s %s %s (%s)' % (
                rec.direction or '',
                rec.operation or '',
                rec.entity_type or '',
                rec.state or '',
            )

    @api.model
    def log_sync(self, **kwargs):
        try:
            return self.sudo().create(kwargs)
        except Exception:
            _logger.exception('Failed to write sync log')
            return self.browse()

    @api.autovacuum
    def _gc_old_logs(self):
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=90)
        self.search([('create_date', '<', limit_date)]).unlink()
