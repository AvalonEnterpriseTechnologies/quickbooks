from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    qb_employee_id = fields.Char(
        string='QB Employee ID', index=True, copy=False, tracking=True,
    )
    qb_hired_date = fields.Date(string='QB Hired Date', copy=False)
    qb_released_date = fields.Date(string='QB Released Date', copy=False)
    qb_employee_type = fields.Char(string='QB Employee Type', copy=False)
    qb_web_addr = fields.Char(string='QB Web Address', copy=False)
    qb_organization = fields.Boolean(string='QB Organization', copy=False)
    qb_use_time_entry = fields.Selection(
        [('use_time_entry', 'Use Time Entry'), ('do_not_use_time_entry', 'Do Not Use Time Entry')],
        string='QB Use Time Entry',
        copy=False,
    )
    qb_default_tax_code_ref = fields.Char(string='QB Default Tax Code Ref', copy=False)
    qb_intuit_id = fields.Char(string='QB Intuit ID', copy=False, tracking=True)
    qb_employment_status = fields.Selection(
        [
            ('active', 'Active'),
            ('terminated', 'Terminated'),
            ('leave', 'Leave'),
            ('inactive', 'Inactive'),
        ],
        string='QB Employment Status',
        default='active',
        copy=False,
    )
    qb_termination_date = fields.Date(string='QB Termination Date', copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False, tracking=True,
    )
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False, tracking=True)
    qb_workers_comp_class_id = fields.Many2one(
        'hr.employee.category',
        string='QB Workers Comp Class',
        ondelete='set null',
    )
    qb_workers_comp_estimated_premium = fields.Float(
        string='Estimated Workers Comp Premium',
        compute='_compute_qb_workers_comp_estimated_premium',
    )

    @api.depends('qb_workers_comp_class_id.qb_workers_comp_rate')
    def _compute_qb_workers_comp_estimated_premium(self):
        for employee in self:
            employee.qb_workers_comp_estimated_premium = (
                employee.qb_workers_comp_class_id.qb_workers_comp_rate or 0.0
            )
