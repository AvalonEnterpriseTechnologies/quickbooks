from odoo import fields, models


class ShopScheduleStage(models.Model):
    _name = 'shop.schedule.stage'
    _description = 'Shop Schedule Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one('shop.schedule.category', string='Category')
    fold = fields.Boolean(
        string='Folded in Kanban',
        help='Fold this stage column in Kanban view when it is empty.',
    )
    color = fields.Integer()
