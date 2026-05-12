from odoo import fields, models


class HrWorkLocation(models.Model):
    _inherit = 'hr.work.location'

    qb_work_location_id = fields.Char(string='QB Work Location ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
