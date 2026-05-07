from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    qb_po_id = fields.Char(string='QB Purchase Order ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
