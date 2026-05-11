from odoo import fields, models


class QuickbooksDataProbe(models.Model):
    _name = 'quickbooks.data.probe'
    _description = 'QuickBooks Data Presence Probe'
    _order = 'company_id, area'
    _rec_name = 'area'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    area = fields.Selection(
        [
            ('recurring_transactions', 'Recurring Transactions'),
            ('bundles', 'Product Bundles'),
            ('projects', 'Projects'),
            ('time_activities', 'Time Activities'),
            ('expenses', 'Expenses'),
            ('payroll_paychecks', 'Payroll Paychecks'),
            ('inventory_items', 'Inventory Items'),
            ('purchase_orders', 'Purchase Orders'),
            ('estimates', 'Estimates'),
            ('sales_receipts', 'Sales Receipts'),
            ('custom_field_definitions', 'Custom Field Definitions'),
            ('attachments', 'Attachments'),
            ('classes', 'Classes'),
            ('departments', 'Departments'),
        ],
        required=True,
        index=True,
    )
    has_data = fields.Boolean(index=True)
    sample_count = fields.Integer()
    last_probed_at = fields.Datetime()
    probe_duration_ms = fields.Integer()
    error_message = fields.Text()

    _area_company_uniq = models.Constraint(
        'unique(company_id, area)',
        'Only one QuickBooks data probe row is allowed per company and area.',
    )
