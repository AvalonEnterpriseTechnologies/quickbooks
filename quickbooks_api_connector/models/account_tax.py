from odoo import fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    qb_taxcode_id = fields.Char(
        string='QB Tax Code ID', index=True, copy=False,
    )
    qb_taxrate_id = fields.Char(
        string='QB Tax Rate ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
