from odoo import fields, models


class QuickbooksRecurringTemplate(models.Model):
    _name = 'quickbooks.recurring.template'
    _description = 'QuickBooks Recurring Transaction Template'
    _order = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    name = fields.Char(required=True)
    qb_recurring_id = fields.Char(string='QB RecurringTransaction ID', index=True, copy=False)
    qb_sync_token = fields.Char(copy=False)
    txn_type = fields.Selection(
        [
            ('Bill', 'Bill'),
            ('Purchase', 'Purchase'),
            ('CreditMemo', 'Credit Memo'),
            ('Deposit', 'Deposit'),
            ('Estimate', 'Estimate'),
            ('Invoice', 'Invoice'),
            ('JournalEntry', 'Journal Entry'),
            ('RefundReceipt', 'Refund Receipt'),
            ('SalesReceipt', 'Sales Receipt'),
            ('Transfer', 'Transfer'),
            ('VendorCredit', 'Vendor Credit'),
            ('PurchaseOrder', 'Purchase Order'),
        ],
        required=True,
    )
    active = fields.Boolean(default=True)
    schedule_type = fields.Char()
    interval_type = fields.Char()
    next_date = fields.Date()
    previous_date = fields.Date()
    raw_json = fields.Json()
    qb_last_synced = fields.Datetime(copy=False)

    _qb_recurring_company_uniq = models.Constraint(
        'unique(company_id, qb_recurring_id)',
        'This QuickBooks recurring transaction is already linked for this company.',
    )
