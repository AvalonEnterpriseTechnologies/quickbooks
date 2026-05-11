from odoo import api, fields, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    qb_account_id = fields.Char(
        string='QB Account ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_opening_balance = fields.Monetary(
        string='QB Opening Balance',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_opening_balance_date = fields.Date(
        string='QB Opening Balance Date',
        copy=False,
    )
    qb_current_balance = fields.Monetary(
        string='QB Current Balance',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_current_balance_with_subaccounts = fields.Monetary(
        string='QB Current Balance With Subaccounts',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_tb_balance = fields.Monetary(
        string='QB Trial Balance (Latest)',
        currency_field='company_currency_id',
        compute='_compute_qb_tb_balance',
    )
    qb_account_type = fields.Char(string='QB Account Type', copy=False)
    qb_account_subtype = fields.Char(string='QB Account Subtype', copy=False)
    qb_account_code = fields.Char(string='QB Account Number', copy=False)
    qb_parent_account_id = fields.Char(string='QB Parent Account ID', copy=False)
    qb_is_subaccount = fields.Boolean(string='QB Sub-account', copy=False)
    qb_fqn = fields.Char(string='QB Fully Qualified Name', copy=False)

    @api.depends('qb_account_id')
    def _compute_qb_tb_balance(self):
        Balance = self.env['quickbooks.account.balance'].sudo()
        for account in self:
            balance = Balance.search([
                ('account_id', '=', account.id),
                ('report_type', '=', 'TrialBalance'),
            ], order='period_end desc, id desc', limit=1)
            if not balance and account.qb_account_id:
                balance = Balance.search([
                    ('qb_account_id', '=', account.qb_account_id),
                    ('report_type', '=', 'TrialBalance'),
                ], order='period_end desc, id desc', limit=1)
            account.qb_tb_balance = balance.balance if balance else 0.0

    def action_view_qbo_balances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Account Balances',
            'res_model': 'quickbooks.account.balance',
            'view_mode': 'list,form',
            'domain': [('qb_account_id', '=', self.qb_account_id)],
            'context': {
                'default_account_id': self.id,
                'default_qb_account_id': self.qb_account_id,
            },
        }

    def action_view_qbo_subaccounts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Sub-accounts',
            'res_model': 'account.account',
            'view_mode': 'list,form',
            'domain': [('qb_parent_account_id', '=', self.qb_account_id)],
        }
