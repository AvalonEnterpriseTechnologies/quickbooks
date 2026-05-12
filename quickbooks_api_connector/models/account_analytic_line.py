from odoo import api, fields, models


class AccountAnalyticLine(models.Model):
    _name = 'account.analytic.line'
    _inherit = ['account.analytic.line', 'mail.thread']

    qb_timeactivity_id = fields.Char(
        string='QB TimeActivity ID', index=True, copy=False, tracking=True,
    )
    qb_timesheet_id = fields.Char(
        string='QB Time (TSheets) ID', index=True, copy=False, tracking=True,
        help='ID from the QuickBooks Time / TSheets API',
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
