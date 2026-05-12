from odoo import api, fields, models


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    qb_purchase_id = fields.Char(string='QB Purchase ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
