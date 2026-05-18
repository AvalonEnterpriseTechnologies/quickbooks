import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


QBO_FEDERAL_FILING_STATUS = {
    'SINGLE': 'single',
    'SINGLE_OR_MARRIED_FILING_SEPARATELY': 'single',
    'MARRIED_JOINTLY': 'married_jointly',
    'MARRIED_FILING_JOINTLY': 'married_jointly',
    'HEAD_OF_HOUSEHOLD': 'head_of_household',
    'EXEMPT': 'exempt',
}

QBO_KS_FILING_STATUS = {
    'SINGLE': 'single',
    'SINGLE_HOH': 'single',
    'HEAD_OF_HOUSEHOLD': 'single',
    'MARRIED': 'married',
    'MARRIED_FILING_JOINTLY': 'married',
    'EXEMPT': 'exempt',
}

QBO_EMPLOYEE_TYPE_TO_CLASS = {
    'W2': 'w2',
    'EMPLOYEE': 'w2',
    'REGULAR': 'w2',
    '1099': '1099_contractor',
    'CONTRACTOR': '1099_contractor',
    '1099_CONTRACTOR': '1099_contractor',
}

QBO_RATE_TYPE = {
    'HOURLY': 'hourly',
    'HOUR': 'hourly',
    'SALARY': 'salary',
    'SALARIED': 'salary',
    'COMMISSION': 'commission',
}


class QBSyncPayrollEmployees(models.AbstractModel):
    _name = 'qb.sync.payroll.employees'
    _description = 'QuickBooks Payroll Employee Cache Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll employee push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_employees_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        payroll_client = self.env['qb.payroll.client']
        if entity_type == 'payroll_tax_setup':
            return self._upsert_tax_setup(
                payroll_client.fetch_employee_tax_setup(config),
                config,
            )
        data = payroll_client.fetch_payroll_employees(config)
        try:
            tax_data = payroll_client.fetch_employee_tax_setup(config)
        except Exception:
            tax_data = {}
            _logger.info(
                'payrollEmployeeTaxSetup not entitled for this app; skipping W-4 import.'
            )
        try:
            comp_data = payroll_client.fetch_compensations(config)
        except Exception:
            comp_data = {}

        count = self._upsert_employees(data, config, tax_data, comp_data)
        if tax_data:
            self._upsert_tax_setup(tax_data, config)
        return count

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll employee push_all; Payroll GraphQL is read-only.')

    # ------------------------------------------------------------------
    # Employee + contract upsert
    # ------------------------------------------------------------------

    def _upsert_employees(self, data, config, tax_data=None, comp_data=None):
        count = 0
        tax_by_employee = self._index_by_employee(
            (tax_data or {}).get('payrollEmployeeTaxSetup') or [],
        )
        comp_by_employee = self._index_compensations(
            (comp_data or {}).get('payrollEmployeeCompensations') or [],
        )
        for employee in data.get('payrollEmployees', []):
            qb_id = str(employee.get('id') or '')
            if not qb_id:
                continue
            odoo_employee = self._find_or_create_employee(employee, config)
            if not odoo_employee:
                continue
            self._update_hr_employee(odoo_employee, employee, config)
            tax_setup = tax_by_employee.get(qb_id) or {}
            if tax_setup:
                self._apply_federal_w4(odoo_employee, tax_setup.get('federalW4') or {})
                self._apply_state_w4(odoo_employee, tax_setup.get('stateW4') or [])
            compensation = comp_by_employee.get(qb_id)
            self._update_contract(odoo_employee, employee, compensation, config)
            count += 1
        return count

    def _index_by_employee(self, rows):
        index = {}
        for row in rows or []:
            qb_id = str(row.get('employeeId') or '')
            if qb_id:
                index[qb_id] = row
        return index

    def _index_compensations(self, rows):
        index = {}
        for row in rows or []:
            qb_id = str(row.get('employeeId') or '')
            comps = row.get('compensations') or []
            if not qb_id or not comps:
                continue
            active = [c for c in comps if c.get('active', True)]
            index[qb_id] = (active[0] if active else comps[0])
        return index

    def _find_or_create_employee(self, payload, config):
        if 'hr.employee' not in self.env:
            return False
        Employee = self.env['hr.employee'].sudo()
        if 'qb_employee_id' not in Employee._fields:
            return False
        qb_id = str(payload.get('id') or '')
        if not qb_id:
            return False
        employee = Employee.search([
            ('qb_employee_id', '=', qb_id),
        ], limit=1)
        if employee:
            return employee
        name_parts = [payload.get('givenName'), payload.get('familyName')]
        name = ' '.join(p for p in name_parts if p) or payload.get('displayName') or qb_id
        return Employee.create({
            'name': name,
            'qb_employee_id': qb_id,
            'company_id': config.company_id.id,
            'work_email': payload.get('email') or False,
            'work_phone': payload.get('phone') or False,
        })

    def _update_hr_employee(self, employee, payload, config):
        vals = {}
        if 'qb_employment_status' in employee._fields:
            vals['qb_employment_status'] = self._normalize_status(
                payload.get('employmentStatus'),
            )
        if 'qb_termination_date' in employee._fields:
            vals['qb_termination_date'] = payload.get('terminationDate') or False
        if 'qb_hired_date' in employee._fields:
            vals['qb_hired_date'] = payload.get('hireDate') or False
        if 'qb_birth_date' in employee._fields and payload.get('birthDate'):
            vals['qb_birth_date'] = payload.get('birthDate')
        if 'qb_ssn_last4' in employee._fields and payload.get('ssn'):
            ssn = str(payload['ssn']).replace('-', '').strip()
            if ssn:
                vals['qb_ssn_last4'] = ssn[-4:]
        if 'qb_employee_classification' in employee._fields:
            token = str(payload.get('employeeType') or '').upper()
            classification = QBO_EMPLOYEE_TYPE_TO_CLASS.get(token)
            if classification:
                vals['qb_employee_classification'] = classification
        if payload.get('email') and 'work_email' in employee._fields:
            vals['work_email'] = payload['email']
        if payload.get('phone') and 'work_phone' in employee._fields:
            vals['work_phone'] = payload['phone']
        birthday = payload.get('birthDate')
        if birthday and 'birthday' in employee._fields:
            vals['birthday'] = birthday

        partner = self._upsert_mailing_address(employee, payload, config)
        if partner and 'address_id' in employee._fields:
            vals['address_id'] = partner.id

        if 'qb_direct_deposit_json' in employee._fields:
            dd = payload.get('directDeposit')
            if dd:
                vals['qb_direct_deposit_json'] = employee._qb_encrypt_direct_deposit(
                    dd, config,
                )
        if 'qb_workers_comp_class_id' in employee._fields:
            wc_id = payload.get('workersCompClassId')
            if wc_id and 'hr.employee.category' in self.env:
                category = self.env['hr.employee.category'].sudo().search([
                    ('qb_workers_comp_code', '=', str(wc_id)),
                ], limit=1)
                if category:
                    vals['qb_workers_comp_class_id'] = category.id
        if 'qb_last_synced' in employee._fields:
            vals['qb_last_synced'] = fields.Datetime.now()
        if vals:
            employee.with_context(skip_qb_sync=True).write(vals)

    def _upsert_mailing_address(self, employee, payload, config):
        address = payload.get('mailingAddress') or payload.get('workAddress')
        if not address or 'res.partner' not in self.env:
            return False
        Partner = self.env['res.partner'].sudo()
        country = self._resolve_country(address.get('country'))
        state = self._resolve_state(address.get('state'), country)
        vals = {
            'name': employee.name,
            'street': address.get('line1') or False,
            'street2': address.get('line2') or False,
            'city': address.get('city') or False,
            'zip': address.get('postalCode') or False,
            'company_id': config.company_id.id,
            'type': 'private',
        }
        if country:
            vals['country_id'] = country.id
        if state:
            vals['state_id'] = state.id
        partner = employee.address_id if 'address_id' in employee._fields else False
        if partner and partner.exists():
            partner.write({k: v for k, v in vals.items() if v not in (False, None)})
            return partner
        return Partner.create({k: v for k, v in vals.items() if v not in (False, None)})

    def _resolve_country(self, code):
        if not code:
            return False
        Country = self.env['res.country'].sudo()
        token = str(code).strip()
        return Country.search([
            '|', ('code', '=', token.upper()), ('name', '=ilike', token),
        ], limit=1)

    def _resolve_state(self, code, country):
        if not code or not country:
            return False
        State = self.env['res.country.state'].sudo()
        return State.search([
            ('country_id', '=', country.id),
            '|', ('code', '=', str(code).upper()), ('name', '=ilike', str(code)),
        ], limit=1)

    # ------------------------------------------------------------------
    # Tax setup (federal + state W-4)
    # ------------------------------------------------------------------

    def _upsert_tax_setup(self, data, config):
        rows = data.get('payrollEmployeeTaxSetup') or []
        count = 0
        for row in rows:
            qb_id = str(row.get('employeeId') or '')
            if not qb_id:
                continue
            employee = self._find_employee(qb_id)
            if not employee:
                continue
            self._apply_federal_w4(employee, row.get('federalW4') or {})
            self._apply_state_w4(employee, row.get('stateW4') or [])
            count += 1
        return count

    def _apply_federal_w4(self, employee, federal):
        if not federal:
            return
        vals = {}
        status = QBO_FEDERAL_FILING_STATUS.get(
            str(federal.get('filingStatus') or '').upper(),
        )
        if status and 'qb_federal_filing_status' in employee._fields:
            vals['qb_federal_filing_status'] = status
        for src, dest in (
            ('multipleJobs', 'qb_federal_multiple_jobs'),
            ('dependentsAmount', 'qb_federal_dependents_amount'),
            ('otherIncome', 'qb_federal_other_income'),
            ('deductions', 'qb_federal_deductions'),
            ('extraWithholding', 'qb_federal_extra_withholding'),
            ('exempt', 'qb_federal_exempt'),
        ):
            if dest in employee._fields and federal.get(src) is not None:
                value = federal[src]
                if dest in (
                    'qb_federal_dependents_amount', 'qb_federal_other_income',
                    'qb_federal_deductions', 'qb_federal_extra_withholding',
                ):
                    try:
                        value = float(value or 0.0)
                    except (TypeError, ValueError):
                        value = 0.0
                vals[dest] = value
        if vals:
            employee.with_context(skip_qb_sync=True).write(vals)

    def _apply_state_w4(self, employee, state_rows):
        if not state_rows:
            return
        payload = {}
        for entry in state_rows:
            code = str(entry.get('stateCode') or '').upper()
            if not code:
                continue
            payload[code] = entry
            if code == 'KS':
                self._apply_kansas_w4(employee, entry)
        if 'qb_state_w4_json' in employee._fields:
            employee.with_context(skip_qb_sync=True).write({
                'qb_state_w4_json': payload,
            })

    def _apply_kansas_w4(self, employee, entry):
        ks_fields = {
            'l10n_ks_filing_status',
            'l10n_ks_total_allowances',
            'l10n_ks_additional_withholding',
            'l10n_ks_exempt',
            'l10n_ks_form_effective_date',
        }
        if not ks_fields.issubset(employee._fields.keys()):
            return
        vals = {}
        status = QBO_KS_FILING_STATUS.get(str(entry.get('filingStatus') or '').upper())
        if status:
            vals['l10n_ks_filing_status'] = status
        try:
            vals['l10n_ks_total_allowances'] = int(entry.get('allowances') or 0)
        except (TypeError, ValueError):
            pass
        try:
            vals['l10n_ks_additional_withholding'] = float(
                entry.get('extraWithholding') or 0.0,
            )
        except (TypeError, ValueError):
            pass
        if entry.get('exempt') is not None:
            vals['l10n_ks_exempt'] = bool(entry['exempt'])
        vals['l10n_ks_form_effective_date'] = (
            entry.get('effectiveDate') or fields.Date.context_today(employee)
        )
        employee.with_context(skip_qb_sync=True).write(vals)

    # ------------------------------------------------------------------
    # Contract upsert
    # ------------------------------------------------------------------

    def _update_contract(self, employee, payload, compensation, config):
        if 'hr.contract' not in self.env:
            return False
        Contract = self.env['hr.contract'].sudo()
        if 'qb_employee_id' not in Contract._fields:
            return False
        contract = Contract.search([
            ('employee_id', '=', employee.id),
            ('company_id', '=', config.company_id.id),
        ], order='date_start desc, id desc', limit=1)
        structure = self._structure_for_schedule(
            payload.get('payScheduleId') or (compensation or {}).get('payScheduleId'),
            config,
        )
        rate_type = QBO_RATE_TYPE.get(
            str((compensation or {}).get('rateType') or '').upper(),
        )
        wage = 0.0
        if compensation and compensation.get('rate') is not None:
            try:
                wage = float(compensation['rate'])
            except (TypeError, ValueError):
                wage = 0.0
        vals = {
            'name': employee.name,
            'employee_id': employee.id,
            'company_id': config.company_id.id,
            'qb_employee_id': payload.get('id') or employee.qb_employee_id,
            'qb_work_location_id': payload.get('workLocationId') or False,
            'qb_pay_schedule_id': payload.get('payScheduleId') or False,
            'qb_employment_status': payload.get('employmentStatus') or False,
            'date_start': payload.get('hireDate') or fields.Date.context_today(self),
            'qb_last_synced': fields.Datetime.now(),
            'qb_raw_json': payload,
            'qb_rate': wage or False,
            'qb_rate_type': rate_type or False,
            'qb_default_hours_per_week': (
                (compensation or {}).get('defaultHoursPerWeek') or False
            ),
        }
        if compensation and compensation.get('id'):
            vals['qb_compensation_id'] = str(compensation['id'])
        if structure and 'qb_pay_schedule_record_id' in Contract._fields:
            vals['qb_pay_schedule_record_id'] = structure.id
        if structure and 'structure_type_id' in Contract._fields and structure.type_id:
            vals['structure_type_id'] = structure.type_id.id
        if 'wage' in Contract._fields and wage:
            vals['wage'] = wage
        if 'wage_type' in Contract._fields and rate_type in ('hourly', 'salary'):
            vals['wage_type'] = 'hourly' if rate_type == 'hourly' else 'monthly'
        if 'schedule_pay' in Contract._fields and structure:
            schedule_pay = structure.type_id.default_schedule_pay if structure.type_id and 'default_schedule_pay' in structure.type_id._fields else False
            if not schedule_pay:
                # Fall back to the structure's qb_frequency map.
                from .sync_payroll_schedules import QBO_FREQUENCY_TO_SCHEDULE_PAY
                token = str(
                    structure.qb_frequency or '',
                ).strip().upper().replace(' ', '')
                schedule_pay = QBO_FREQUENCY_TO_SCHEDULE_PAY.get(token)
            if schedule_pay:
                vals['schedule_pay'] = schedule_pay
        if 'resource_calendar_id' in Contract._fields and not contract:
            vals['resource_calendar_id'] = (
                employee.resource_calendar_id.id
                or config.company_id.resource_calendar_id.id
            )
        vals = {key: value for key, value in vals.items() if key in Contract._fields}
        if contract:
            contract.write(vals)
            return contract
        return Contract.create(vals)

    def _structure_for_schedule(self, qb_pay_schedule_id, config):
        if not qb_pay_schedule_id or 'hr.payroll.structure' not in self.env:
            return False
        Structure = self.env['hr.payroll.structure'].sudo()
        if 'qb_pay_schedule_id' not in Structure._fields:
            return False
        domain = [('qb_pay_schedule_id', '=', str(qb_pay_schedule_id))]
        if 'company_id' in Structure._fields:
            domain.append(('company_id', '=', config.company_id.id))
        return Structure.search(domain, limit=1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_employee(self, qb_employee_id):
        if 'hr.employee' not in self.env:
            return False
        if 'qb_employee_id' not in self.env['hr.employee']._fields:
            return False
        return self.env['hr.employee'].sudo().search([
            ('qb_employee_id', '=', qb_employee_id),
        ], limit=1)

    @staticmethod
    def _normalize_status(status):
        status = str(status or '').lower()
        if 'term' in status:
            return 'terminated'
        if 'leave' in status:
            return 'leave'
        if 'inactive' in status:
            return 'inactive'
        return 'active'
