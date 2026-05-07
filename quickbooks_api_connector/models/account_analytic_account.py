from odoo import api, fields, models


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    qb_class_id = fields.Char(string='QB Class ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
