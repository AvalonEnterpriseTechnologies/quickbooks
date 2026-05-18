import logging

from odoo import models

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
        if 'qb.payroll.check' not in self.env:
            _logger.warning(
                "QuickBooks payroll archive model not loaded - skipping benefit "
                "sync (install hr_payroll + hr_contract)"
            )
            return 0
        Check = self.env['qb.payroll.check'].sudo()
        Line = self.env['qb.payroll.check.line'].sudo()
        count = 0
        for payload in data.get('payrollChecks') or []:
            qb_id = str(payload.get('id') or '')
            if not qb_id:
                continue
            check = Check.search([
                ('company_id', '=', config.company_id.id),
                ('qb_check_id', '=', qb_id),
            ], limit=1)
            if not check:
                continue
            for raw_line in self._benefit_lines(payload):
                Line.create({
                    'check_id': check.id,
                    'line_type': 'benefit',
                    'is_employer_side': bool(raw_line.get('employer')),
                    'qb_pay_item_id': str(raw_line.get('payItemId') or '') or False,
                    'name': raw_line.get('name') or raw_line.get('type') or 'Benefit',
                    'code': (raw_line.get('name') or '')[:64] or False,
                    'qb_benefit_type': self._benefit_type(
                        raw_line.get('name'), raw_line.get('type'),
                    ),
                    'amount': self._amount(raw_line.get('amount')),
                    'qb_raw_json': raw_line,
                })
                count += 1
        return count

    def _benefit_lines(self, check):
        lines = []
        for key in (
            'benefits', 'employeeBenefits',
            'deductions', 'employeeDeductions',
        ):
            value = check.get(key) or []
            if isinstance(value, dict):
                value = value.get('items') or value.get('nodes') or []
            for line in value:
                if isinstance(line, dict):
                    lines.append(line)
        return lines

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
        text = ('%s %s' % (name or '', line_type or '')).lower()
        if any(token in text for token in ('health', 'medical', 'dental', 'vision')):
            return 'health'
        if any(token in text for token in ('401', 'retirement', 'ira', 'simple')):
            return 'retirement'
        if any(token in text for token in ('garnish', 'levy', 'child support')):
            return 'garnishment'
        return 'other'
