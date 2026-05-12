from odoo import fields, models


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'

    qb_definition_id = fields.Char(string='QB Custom Field Definition ID', index=True, copy=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
