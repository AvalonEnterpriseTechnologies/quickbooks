from odoo import fields, models


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
    qb_account_type = fields.Char(string='QB Account Type', copy=False)
    qb_account_subtype = fields.Char(string='QB Account Subtype', copy=False)
    qb_account_code = fields.Char(string='QB Account Number', copy=False)

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
