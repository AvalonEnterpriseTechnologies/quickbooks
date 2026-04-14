from odoo import fields, models


class ShopScheduleCategory(models.Model):
    _name = 'shop.schedule.category'
    _description = 'Shop Schedule Stage Category'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    stage_ids = fields.One2many('shop.schedule.stage', 'category_id', string='Stages')
