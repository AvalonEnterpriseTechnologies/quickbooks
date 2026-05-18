from odoo import fields, models


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    qb_payslip_run_id = fields.Char(
        string='QB Payslip Run ID',
        index=True,
        copy=False,
        help='Stable key used by qb.sync.payroll.payslips to upsert a '
             'payslip batch idempotently. Normally derived from the QBO '
             'pay-period end date so re-running the backfill never creates '
             'duplicate batches.',
    )
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)

    _qb_payslip_run_uniq = models.Constraint(
        'unique(company_id, qb_payslip_run_id)',
        'A QuickBooks payslip run can only be imported once per company.',
    )
