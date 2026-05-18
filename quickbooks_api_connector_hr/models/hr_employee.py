from odoo import api, fields, models


PAYROLL_USER_GROUP = 'hr_payroll.group_hr_payroll_user'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    qb_employee_id = fields.Char(
        string='QB Employee ID', index=True, copy=False, tracking=True,
    )
    qb_hired_date = fields.Date(string='QB Hired Date', copy=False)
    qb_released_date = fields.Date(string='QB Released Date', copy=False)
    qb_employee_type = fields.Char(string='QB Employee Type', copy=False)
    qb_employee_classification = fields.Selection(
        [
            ('w2', 'W-2 Employee'),
            ('1099_contractor', '1099 Contractor'),
        ],
        string='QB Employee Classification',
        copy=False,
    )
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

    qb_ssn_last4 = fields.Char(
        string='QB SSN Last 4',
        copy=False,
        groups=PAYROLL_USER_GROUP,
        help='Last four digits of the SSN as reported by QuickBooks. Full SSNs '
             'go into the native Odoo encrypted field; this is a non-sensitive '
             'reference for quick matching.',
    )
    qb_birth_date = fields.Date(
        string='QB Birth Date',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_filing_status = fields.Selection(
        [
            ('single', 'Single or Married Filing Separately'),
            ('married_jointly', 'Married Filing Jointly'),
            ('head_of_household', 'Head of Household'),
            ('exempt', 'Exempt'),
        ],
        string='QB Federal W-4 Filing Status',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_multiple_jobs = fields.Boolean(
        string='QB Federal W-4 Multiple Jobs',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_dependents_amount = fields.Monetary(
        string='QB Federal W-4 Dependents Amount',
        currency_field='currency_id',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_other_income = fields.Monetary(
        string='QB Federal W-4 Other Income',
        currency_field='currency_id',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_deductions = fields.Monetary(
        string='QB Federal W-4 Deductions',
        currency_field='currency_id',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_extra_withholding = fields.Monetary(
        string='QB Federal W-4 Extra Withholding',
        currency_field='currency_id',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_federal_exempt = fields.Boolean(
        string='QB Federal W-4 Exempt',
        copy=False,
        groups=PAYROLL_USER_GROUP,
    )
    qb_state_w4_json = fields.Json(
        string='QB State W-4 Setup',
        copy=False,
        groups=PAYROLL_USER_GROUP,
        help='Full state-W-4 payload keyed by state code. Stored verbatim so '
             'future state localizations can consume it without a re-import.',
    )
    qb_direct_deposit_json = fields.Json(
        string='QB Direct Deposit',
        copy=False,
        groups=PAYROLL_USER_GROUP,
        help='Direct deposit allocation as returned by QBO Payroll. Stored '
             'encrypted at rest; never echoed to the chatter or sync log.',
    )
    qb_payroll_archived = fields.Boolean(
        string='QB Payroll Archived',
        default=False,
        copy=False,
        groups=PAYROLL_USER_GROUP,
        help='Set after the QBO -> Odoo payroll cutover for this employee. '
             'The daily payroll-check cron skips archived employees.',
    )

    @api.depends('qb_workers_comp_class_id.qb_workers_comp_rate')
    def _compute_qb_workers_comp_estimated_premium(self):
        for employee in self:
            employee.qb_workers_comp_estimated_premium = (
                employee.qb_workers_comp_class_id.qb_workers_comp_rate or 0.0
            )

    _QB_DIRECT_DEPOSIT_SECRETS = (
        'bankRoutingNumber',
        'bankAccountNumber',
        'routingNumber',
        'accountNumber',
    )

    @api.model
    def _qb_encrypt_direct_deposit(self, payload, config=None):
        """Return a copy of ``payload`` with sensitive bank fields encrypted.

        The Fernet key from ``quickbooks.config._get_fernet`` is reused so
        that operations / DR procedures only deal with one key. When the
        cryptography library is unavailable the helper falls back to the
        same base64 obfuscation that the connector uses for tokens — far
        from ideal but consistent with the rest of the surface.
        """
        if not payload:
            return payload
        if isinstance(payload, list):
            return [self._qb_encrypt_direct_deposit(item, config) for item in payload]
        if not isinstance(payload, dict):
            return payload

        if config is None:
            config = self.env['quickbooks.config'].sudo().search(
                [('company_id', '=', (self.company_id or self.env.company).id)],
                limit=1,
            )
        if not config:
            return payload

        result = dict(payload)
        for key in self._QB_DIRECT_DEPOSIT_SECRETS:
            value = result.get(key)
            if value and not str(value).startswith('enc:'):
                cipher = config._encrypt(str(value))
                if cipher:
                    result[key] = 'enc:%s' % cipher
        for nested_key in ('accounts', 'allocations'):
            if isinstance(result.get(nested_key), list):
                result[nested_key] = [
                    self._qb_encrypt_direct_deposit(item, config)
                    for item in result[nested_key]
                ]
        return result
