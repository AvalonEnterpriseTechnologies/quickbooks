from odoo import fields, models


class ShopScheduleOperation(models.Model):
    _name = 'shop.schedule.operation'
    _description = 'Shop Schedule Operation (Routing Step)'
    _order = 'sequence, op_number, id'

    order_id = fields.Many2one(
        'shop.schedule.order',
        string='Work Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    op_number = fields.Integer(string='Op #', help='ProShop operation number (10, 30, 50, ...)')
    name = fields.Char(string='Description', required=True, help='Operation description, e.g. GRIND RADIUS')
    resource = fields.Char(string='Resource', help='Machine or resource, e.g. MIL-VF3 (VF3)')
    sequence = fields.Integer(default=10)
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('complete', 'Complete'),
        ],
        default='pending',
    )
    is_complete = fields.Boolean(string='Complete')
    notes = fields.Text()
