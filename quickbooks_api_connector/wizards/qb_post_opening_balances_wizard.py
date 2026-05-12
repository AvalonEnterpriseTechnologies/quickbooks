from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class QBPostOpeningBalancesWizard(models.TransientModel):
    _name = 'qb.post.opening.balances.wizard'
    _description = 'Post QuickBooks Opening Balances'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    as_of_date = fields.Date(required=True, default=lambda self: self._default_as_of_date())
    snapshot_id = fields.Many2one(
        'qb.balance.variance',
        domain="[('report_type', '=', 'TrialBalance'), ('company_id', '=', company_id)]",
        required=True,
    )
    target_journal_id = fields.Many2one(
        'account.journal',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        required=True,
        default=lambda self: self._default_opening_journal(),
    )
    opening_equity_account_id = fields.Many2one(
        'account.account',
        required=True,
        default=lambda self: self._default_opening_equity_account(),
    )
    retained_earnings_account_id = fields.Many2one(
        'account.account',
        required=True,
        default=lambda self: self._default_retained_earnings_account(),
    )
    allow_unmatched_to_opening_equity = fields.Boolean(
        string='Post Unmatched Rows To Opening Equity',
        default=False,
    )
    lock_books_at_as_of_date = fields.Boolean(
        string='Lock Books At As-Of Date',
        default=False,
    )
    dry_run = fields.Boolean(default=True)
    preview_message = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        company = self.env['res.company'].browse(
            vals.get('company_id') or self.env.company.id,
        )
        snapshot = self._latest_trial_balance_snapshot(company, vals.get('as_of_date'))
        if snapshot:
            vals.setdefault('snapshot_id', snapshot.id)
            vals['as_of_date'] = snapshot.period_end
        return vals

    def action_post_opening_balances(self):
        self.ensure_one()
        lines = self._opening_lines()
        if not lines:
            raise UserError('No Trial Balance rows with linked Odoo accounts were found.')
        if self.dry_run:
            debit = sum(line[2]['debit'] for line in lines)
            credit = sum(line[2]['credit'] for line in lines)
            self.preview_message = (
                'Dry run: %d account lines. Debits %.2f, credits %.2f.'
            ) % (len(lines), debit, credit)
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        existing = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('qb_opening_snapshot_id', '=', self.snapshot_id.id),
            ('state', '=', 'posted'),
        ], limit=1)
        if existing:
            raise UserError(
                'Opening balances for this QuickBooks Trial Balance snapshot '
                'were already posted in %s.' % existing.display_name
            )

        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'entry',
            'company_id': self.company_id.id,
            'date': self.as_of_date,
            'journal_id': self.target_journal_id.id,
            'ref': 'QuickBooks Opening Balances %s' % self.as_of_date,
            'qb_opening_snapshot_id': self.snapshot_id.id,
            'qb_do_not_sync': True,
            'line_ids': lines,
        })
        move.with_context(skip_qb_sync=True).action_post()
        if self.lock_books_at_as_of_date and 'fiscalyear_lock_date' in self.company_id._fields:
            self.company_id.write({'fiscalyear_lock_date': self.as_of_date})
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Opening Balance Entry',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
        }

    def _opening_lines(self):
        balances = self.env['qb.balance.variance'].search([
            ('report_type', '=', 'TrialBalance'),
            ('company_id', '=', self.company_id.id),
            ('period_end', '=', self.snapshot_id.period_end),
        ], order='label')
        lines = []
        debit_total = credit_total = 0.0
        pnl_balance = 0.0
        unmatched = []
        for balance in balances:
            account = balance.account_id
            if not account:
                unmatched.append(balance)
                continue
            amount = balance.qb_amount or 0.0
            if not self._is_balance_sheet_account(account):
                pnl_balance += amount
                continue
            debit = amount if amount > 0 else 0.0
            credit = abs(amount) if amount < 0 else 0.0
            if not debit and not credit:
                continue
            debit_total += debit
            credit_total += credit
            lines.append((0, 0, {
                'name': balance.label,
                'account_id': account.id,
                'debit': debit,
                'credit': credit,
            }))
        if unmatched and not self.allow_unmatched_to_opening_equity:
            raise UserError(
                'The following QuickBooks Trial Balance rows are not linked to '
                'Odoo accounts: %s. Link the accounts first or enable posting '
                'unmatched rows to Opening Equity.'
                % ', '.join(unmatched.mapped('label'))
            )
        if unmatched and self.allow_unmatched_to_opening_equity:
            for balance in unmatched:
                amount = balance.qb_amount or 0.0
                debit = amount if amount > 0 else 0.0
                credit = abs(amount) if amount < 0 else 0.0
                if not debit and not credit:
                    continue
                debit_total += debit
                credit_total += credit
                lines.append((0, 0, {
                    'name': 'Unmatched QB row: %s' % balance.label,
                    'account_id': self.opening_equity_account_id.id,
                    'debit': debit,
                    'credit': credit,
                }))
        if round(pnl_balance, 2):
            debit = pnl_balance if pnl_balance > 0 else 0.0
            credit = abs(pnl_balance) if pnl_balance < 0 else 0.0
            debit_total += debit
            credit_total += credit
            lines.append((0, 0, {
                'name': 'QuickBooks YTD P&L rollup to retained earnings',
                'account_id': self.retained_earnings_account_id.id,
                'debit': debit,
                'credit': credit,
            }))
        delta = round(debit_total - credit_total, 2)
        if delta:
            lines.append((0, 0, {
                'name': 'QuickBooks opening balance offset',
                'account_id': self.opening_equity_account_id.id,
                'debit': abs(delta) if delta < 0 else 0.0,
                'credit': delta if delta > 0 else 0.0,
            }))
        return lines

    @staticmethod
    def _is_balance_sheet_account(account):
        account_type = account.account_type or ''
        return account_type.startswith(('asset_', 'liability_', 'equity'))

    @api.model
    def _latest_trial_balance_snapshot(self, company, as_of_date=None):
        domain = [
            ('company_id', '=', company.id),
            ('report_type', '=', 'TrialBalance'),
        ]
        if as_of_date:
            domain.append(('period_end', '<=', as_of_date))
        return self.env['qb.balance.variance'].search(
            domain, order='period_end desc, fetched_at desc', limit=1,
        )

    @api.model
    def _default_as_of_date(self):
        today = fields.Date.context_today(self)
        first = date(today.year, today.month, 1)
        return first - timedelta(days=1)

    @api.model
    def _default_opening_journal(self):
        config = self.env['quickbooks.config'].search([
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if config:
            return self.env['qb.sync.journals'].ensure_general_journal(
                config, key='qbo:general:opening',
                name='QuickBooks Opening Balances',
            )
        return self.env['account.journal'].search([
            ('company_id', '=', self.env.company.id),
            ('type', '=', 'general'),
        ], limit=1)

    @api.model
    def _default_opening_equity_account(self):
        return self._opening_equity_account(self.env.company)

    @api.model
    def _default_retained_earnings_account(self):
        return self._retained_earnings_account(self.env.company)

    @api.model
    def _opening_equity_account(self, company):
        Account = self.env['account.account'].sudo()
        domain = [('account_type', '=', 'equity_unaffected')]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', company.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', '=', company.id))
        account = Account.search(domain, limit=1)
        if account:
            return account
        vals = {
            'name': 'Opening Balance Equity',
            'code': self._available_account_code('3900', company),
            'account_type': 'equity_unaffected',
        }
        if 'company_id' in Account._fields:
            vals['company_id'] = company.id
        elif 'company_ids' in Account._fields:
            vals['company_ids'] = [(4, company.id)]
        return Account.with_context(skip_qb_sync=True).create(vals)

    @api.model
    def _retained_earnings_account(self, company):
        Account = self.env['account.account'].sudo()
        domain = [('account_type', '=', 'equity_unaffected')]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', company.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', '=', company.id))
        account = Account.search(domain, limit=1)
        if account:
            return account
        return self._opening_equity_account(company)

    def _available_account_code(self, code, company):
        Account = self.env['account.account'].sudo()
        domain = [('code', '=', code)]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', company.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', '=', company.id))
        if not Account.search(domain, limit=1):
            return code
        company_domain = [
            term for term in domain
            if not isinstance(term, tuple) or term[0] != 'code'
        ]
        index = 2
        while True:
            candidate = '%s%s' % (code, index)
            if not Account.search(company_domain + [('code', '=', candidate)], limit=1):
                return candidate
            index += 1
