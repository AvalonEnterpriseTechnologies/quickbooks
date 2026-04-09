from odoo import fields, models


class QuickbooksFieldMapping(models.Model):
    _name = 'quickbooks.field.mapping'
    _description = 'QuickBooks Field Mapping'
    _order = 'entity_type, sequence'

    entity_type = fields.Selection(
        [('customer', 'Customer'),
         ('vendor', 'Vendor'),
         ('product', 'Product'),
         ('account', 'Account'),
         ('invoice', 'Invoice'),
         ('bill', 'Bill'),
         ('payment', 'Payment'),
         ('bill_payment', 'Bill Payment'),
         ('journal_entry', 'Journal Entry'),
         ('credit_memo', 'Credit Memo'),
         ('estimate', 'Estimate'),
         ('tax_code', 'Tax Code')],
        required=True, index=True,
    )
    sequence = fields.Integer(default=10)
    odoo_field = fields.Char(string='Odoo Field Path', required=True)
    qb_field = fields.Char(string='QB Field Path', required=True)
    direction = fields.Selection(
        [('both', 'Bidirectional'),
         ('push', 'Odoo → QBO Only'),
         ('pull', 'QBO → Odoo Only')],
        default='both', required=True,
    )
    transform = fields.Selection(
        [('none', 'No Transform'),
         ('upper', 'Uppercase'),
         ('lower', 'Lowercase'),
         ('bool_to_str', 'Boolean → String'),
         ('date_format', 'Date Format')],
        default='none',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
