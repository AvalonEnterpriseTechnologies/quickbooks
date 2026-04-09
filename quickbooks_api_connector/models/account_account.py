from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    qb_account_id = fields.Char(
        string='QB Account ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
