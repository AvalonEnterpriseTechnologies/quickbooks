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
        Benefit = self.env['quickbooks.employee.benefit'].sudo()
        amount = self._amount(line.get('amount') or line.get('Amount'))
        name = line.get('name') or line.get('Name') or line.get('type') or 'Benefit'
        vals = {
            'company_id': config.company_id.id,
            'employee_id': self._employee_id(check),
            'qb_employee_id': check.get('employeeId') or '',
            'employee_name': check.get('displayName') or '',
            'benefit_type': self._benefit_type(name, line.get('type')),
            'name': name,
            'amount': amount,
            'period_start': check.get('payPeriodStart') or False,
            'period_end': check.get('payPeriodEnd') or check.get('checkDate') or False,
            'source_check_id': check.get('id') or '',
            'raw_json': line,
            'currency_id': config.company_id.currency_id.id,
        }
        existing = Benefit.search([
            ('company_id', '=', config.company_id.id),
            ('source_check_id', '=', vals['source_check_id']),
            ('qb_employee_id', '=', vals['qb_employee_id']),
            ('name', '=', vals['name']),
            ('amount', '=', vals['amount']),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Benefit.create(vals)

    def _employee_id(self, check):
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
