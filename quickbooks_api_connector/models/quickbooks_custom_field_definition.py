from odoo import fields, models


class QuickbooksCustomFieldDefinition(models.Model):
    _name = 'quickbooks.custom.field.definition'
    _description = 'QuickBooks Custom Field Definition'
    _order = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    qb_definition_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    entity_type = fields.Char(index=True)
    field_type = fields.Char()
    active = fields.Boolean(default=True)
    raw_json = fields.Json()
    qb_last_synced = fields.Datetime(copy=False)

    _qb_custom_field_definition_uniq = models.Constraint(
        'unique(company_id, qb_definition_id)',
        'This QuickBooks custom field definition is already linked for this company.',
    )
