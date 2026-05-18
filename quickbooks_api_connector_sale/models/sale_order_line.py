from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    qb_line_id = fields.Char(
        string='QB Line Id',
        index=True,
        copy=False,
        help='QuickBooks Online line Id (Line.Id) preserved verbatim so the '
             'historical import can rebuild line-level links between Estimate '
             'lines and Invoice lines.',
    )
