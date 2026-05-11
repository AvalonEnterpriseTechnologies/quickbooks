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
    row_ids = fields.One2many('quickbooks.report.row', 'snapshot_id')

    _snapshot_unique = models.Constraint(
        'unique(company_id, report_type, period_start, period_end, accounting_method, schema_version)',
        'A report snapshot already exists for this company, report, period, method, and schema version.',
    )

    def action_print_qbo_report(self):
        self.ensure_one()
        return self.env.ref(
            'quickbooks_api_connector.action_report_qb_snapshot',
        ).report_action(self)

    def action_open_native_odoo_report(self):
        self.ensure_one()
        if self.report_type == 'GeneralLedger':
            return self._native_gl_action()
        xml_ids = self._native_report_xml_ids()
        for xml_id in xml_ids.get(self.report_type, []):
            action = self.env.ref(xml_id, raise_if_not_found=False)
            if action:
                result = action.read()[0]
                if not isinstance(result.get('context'), dict):
                    result['context'] = {}
                result['context'] = dict(
                    result['context'],
                    date_to=fields.Date.to_string(self.period_end),
                    default_company_id=self.company_id.id,
                )
                return result
        return self._native_gl_action()

    def _native_gl_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Odoo Journal Items',
            'res_model': 'account.move.line',
            'view_mode': 'list,pivot,graph',
            'domain': [
                ('company_id', '=', self.company_id.id),
                ('date', '<=', self.period_end),
                ('parent_state', '=', 'posted'),
            ],
            'context': {'search_default_group_by_account': 1},
        }

    @staticmethod
    def _native_report_xml_ids():
        return {
            'BalanceSheet': [
                'account_reports.action_account_report_bs',
                'account_reports.account_financial_report_balance_sheet',
            ],
            'ProfitAndLoss': [
                'account_reports.action_account_report_pl',
                'account_reports.account_financial_report_profitandloss',
            ],
            'TrialBalance': [
                'account_reports.action_account_report_tb',
            ],
        }


class QuickbooksReportRow(models.Model):
    _name = 'quickbooks.report.row'
    _description = 'QuickBooks Hierarchical Report Row'
    _order = 'snapshot_id, sequence, id'
    _parent_name = 'parent_id'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True,
    )
    snapshot_id = fields.Many2one(
        'quickbooks.report.snapshot', required=True, ondelete='cascade', index=True,
    )
    parent_id = fields.Many2one('quickbooks.report.row', ondelete='cascade', index=True)
    child_ids = fields.One2many('quickbooks.report.row', 'parent_id')
    sequence = fields.Integer(default=10, index=True)
    level = fields.Integer(default=0)
    path = fields.Char(index=True)
    label = fields.Char(required=True)
    amount = fields.Monetary(currency_field='currency_id')
    is_total = fields.Boolean(index=True)
    is_section = fields.Boolean(index=True)
    qb_account_id = fields.Char(index=True)
    account_id = fields.Many2one('account.account', index=True)
    report_type = fields.Selection(
        related='snapshot_id.report_type', store=True, readonly=True, index=True,
    )
    period_end = fields.Date(
        related='snapshot_id.period_end', store=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
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
