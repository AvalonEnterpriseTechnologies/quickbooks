from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    qb_attachment_id = fields.Char(string='QB Attachment ID', index=True, copy=False)
