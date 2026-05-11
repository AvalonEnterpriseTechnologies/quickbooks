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
