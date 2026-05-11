from odoo import fields, models


class QuickbooksReportSnapshot(models.Model):
    _name = 'quickbooks.report.snapshot'
    _description = 'QuickBooks Report Snapshot'
    _order = 'period_end desc, report_type'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True,
    )
    report_type = fields.Selection(
        [
            ('BalanceSheet', 'Balance Sheet'),
            ('ProfitAndLoss', 'Profit and Loss'),
            ('TrialBalance', 'Trial Balance'),
            ('GeneralLedger', 'General Ledger'),
            ('WorkersCompensation', 'Workers Compensation'),
        ],
        required=True,
        index=True,
    )
    period_start = fields.Date(index=True)
    period_end = fields.Date(required=True, index=True)
    accounting_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        default='Accrual',
        required=True,
    )
    schema_version = fields.Selection(
        [('v1', 'Reports v1'), ('v2', 'Reports v2')],
        default='v1',
        required=True,
    )
    raw_json = fields.Json()
    fetched_at = fields.Datetime(default=fields.Datetime.now, required=True)
    row_count = fields.Integer()

    _snapshot_unique = models.Constraint(
        'unique(company_id, report_type, period_start, period_end, accounting_method, schema_version)',
        'A report snapshot already exists for this company, report, period, method, and schema version.',
    )


class QuickbooksAccountBalance(models.Model):
    _name = 'quickbooks.account.balance'
    _description = 'QuickBooks Account Balance Snapshot'
    _order = 'period_end desc, account_name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True,
    )
    account_id = fields.Many2one('account.account', index=True)
    qb_account_id = fields.Char(index=True)
    account_name = fields.Char(required=True)
    report_type = fields.Selection(
        [('BalanceSheet', 'Balance Sheet'), ('TrialBalance', 'Trial Balance')],
        required=True,
        index=True,
    )
    period_end = fields.Date(required=True, index=True)
    accounting_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        default='Accrual',
        required=True,
    )
    debit_balance = fields.Monetary(currency_field='currency_id')
    credit_balance = fields.Monetary(currency_field='currency_id')
    balance = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    snapshot_id = fields.Many2one(
        'quickbooks.report.snapshot', ondelete='cascade', index=True,
    )


class QuickbooksJournalBalance(models.Model):
    _name = 'quickbooks.journal.balance'
    _description = 'QuickBooks Journal Balance Snapshot'
    _order = 'period_end desc, journal_code'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True,
    )
    journal_code = fields.Char(required=True, index=True)
    journal_name = fields.Char()
    period_end = fields.Date(required=True, index=True)
    accounting_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        default='Accrual',
        required=True,
    )
    debit_balance = fields.Monetary(currency_field='currency_id')
    credit_balance = fields.Monetary(currency_field='currency_id')
    balance = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    snapshot_id = fields.Many2one(
        'quickbooks.report.snapshot', ondelete='cascade', index=True,
    )
