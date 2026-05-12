from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    qb_attachment_id = fields.Char(string='QB Attachment ID', index=True, copy=False)
    qb_attachable_id = fields.Char(string='QB Attachable ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_category = fields.Char(string='QB Category', copy=False)
    qb_tag = fields.Char(string='QB Tag', copy=False)
