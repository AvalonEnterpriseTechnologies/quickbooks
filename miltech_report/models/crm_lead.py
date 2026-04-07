from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    has_po = fields.Boolean(
        string='Has PO',
        compute='_compute_has_po',
        store=True,
        help='Indicates whether a PO Number has been assigned to this opportunity',
    )

    @api.depends('x_studio_po_number')
    def _compute_has_po(self):
        for lead in self:
            lead.has_po = bool(lead.x_studio_po_number)
