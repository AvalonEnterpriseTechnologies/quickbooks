import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncEmployeeBenefits(models.AbstractModel):
    _name = 'qb.sync.employee.benefits'
    _description = 'QuickBooks Employee Benefits Sync (read only)'

    def pull(self, client, config, job):
        return self.pull_all(client, config, 'employee_benefit')

    def push(self, client, config, job):
        _logger.info('Employee benefits are read-only from QuickBooks Payroll.')
        return {}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return {'count': 0}
        data = self.env['qb.payroll.client'].fetch_checks(config)
        return {'count': self._upsert_benefits(config, data)}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping employee benefit push_all; benefits are read-only.')
        return {}

    def _upsert_benefits(self, config, data):
        count = 0
        for check in data.get('payrollChecks') or []:
            lines = self._benefit_lines(check)
            for line in lines:
                self._upsert_line(config, check, line)
                count += 1
        return count

    def _benefit_lines(self, check):
        lines = []
        for key in ('deductions', 'benefits', 'employeeDeductions', 'employeeBenefits'):
            value = check.get(key) or []
            if isinstance(value, dict):
                value = value.get('items') or value.get('nodes') or []
            for line in value:
                if isinstance(line, dict):
                    lines.append(line)
        return lines

    def _upsert_line(self, config, check, line):
        if 'hr.payslip.input' not in self.env:
            _logger.warning("hr_payroll module not installed — skipping benefit line")
            return False
        Benefit = self.env['hr.payslip.input'].sudo()
        if 'qb_source_check_id' not in Benefit._fields:
            _logger.warning(
                "QuickBooks payroll bridge fields are not loaded — skipping benefit line"
            )
            return False
        amount = self._amount(line.get('amount') or line.get('Amount'))
        name = line.get('name') or line.get('Name') or line.get('type') or 'Benefit'
        payslip = self._payslip(check, config)
        vals = {
            'payslip_id': payslip.id if payslip else False,
            'qb_employee_id': check.get('employeeId') or '',
            'qb_benefit_type': self._benefit_type(name, line.get('type')),
            'name': name,
            'code': name[:64],
            'amount': amount,
            'qb_source_check_id': check.get('id') or '',
            'qb_raw_json': line,
        }
        vals = {key: value for key, value in vals.items() if key in Benefit._fields}
        existing = Benefit.search([
            ('qb_source_check_id', '=', vals.get('qb_source_check_id')),
            ('qb_employee_id', '=', vals['qb_employee_id']),
            ('name', '=', vals['name']),
            ('amount', '=', vals['amount']),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Benefit.create(vals)

    def _payslip(self, check, config):
        if 'hr.payslip' not in self.env:
            return False
        qb_check_id = check.get('id') or ''
        return self.env['hr.payslip'].sudo().search([
            ('company_id', '=', config.company_id.id),
            ('qb_check_id', '=', qb_check_id),
        ], limit=1)

    def _employee_id(self, check):
        if 'qb_employee_id' not in self.env['hr.employee']._fields:
            return False
        employee = self.env['hr.employee'].sudo().search([
            ('qb_employee_id', '=', check.get('employeeId') or ''),
        ], limit=1)
        return employee.id if employee else False

    @staticmethod
    def _amount(value):
        if isinstance(value, dict):
            value = value.get('value') or value.get('amount')
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _benefit_type(name, line_type=None):
        text = '%s %s' % (name or '', line_type or '')
        text = text.lower()
        if any(token in text for token in ('health', 'medical', 'dental', 'vision')):
            return 'health'
        if any(token in text for token in ('401', 'retirement', 'ira', 'simple')):
            return 'retirement'
        if any(token in text for token in ('garnish', 'levy', 'child support')):
            return 'garnishment'
        return 'other'
