from odoo import fields, models


class ShopScheduleTag(models.Model):
    _name = 'shop.schedule.tag'
    _description = 'Shop Schedule Tag'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer()
