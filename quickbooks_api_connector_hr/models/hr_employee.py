from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    qb_employee_id = fields.Char(string='QB Employee ID', index=True, copy=False)
    qb_work_location_id = fields.Char(string='QB Work Location ID', index=True, copy=False)
    qb_pay_schedule_id = fields.Char(string='QB Pay Schedule ID', index=True, copy=False)
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
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
    qb_workers_comp_class_id = fields.Many2one(
        'quickbooks.workers.comp.class',
        string='QB Workers Comp Class',
        ondelete='set null',
    )
    qb_workers_comp_estimated_premium = fields.Float(
        string='Estimated Workers Comp Premium',
        compute='_compute_qb_workers_comp_estimated_premium',
    )

    @api.depends('qb_workers_comp_class_id.base_rate')
    def _compute_qb_workers_comp_estimated_premium(self):
        for employee in self:
            employee.qb_workers_comp_estimated_premium = (
                employee.qb_workers_comp_class_id.base_rate or 0.0
            )
