import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


PAYMENT_METHOD_MAP = {
    'DIRECT_DEPOSIT': 'direct_deposit',
    'DD': 'direct_deposit',
    'CHECK': 'check',
    'PAPER_CHECK': 'check',
    'CASH': 'cash',
}

STATUS_MAP = {
    'PAID': 'paid',
    'COMPLETED': 'paid',
    'DRAFT': 'draft',
    'PENDING': 'draft',
    'VOID': 'void',
    'VOIDED': 'void',
    'REVERSED': 'reversed',
}


class QBSyncPayrollChecks(models.AbstractModel):
    _name = 'qb.sync.payroll.checks'
    _description = 'QuickBooks Payroll Check Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll check push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_checks_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return 0
        data = self.env['qb.payroll.client'].fetch_checks(config)
        return self._upsert_checks(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll check push_all; Payroll GraphQL is read-only.')

    def cron_pull_for_all_companies(self):
        """Backward-compatible entry point used by legacy cron records."""
        configs = self.env['quickbooks.config'].search([
            ('state', '=', 'connected'),
            ('payroll_enabled', '=', True),
        ])
        for config in configs:
            if getattr(config, 'qb_payroll_archived', False):
                continue
            try:
                self.pull_all(None, config, 'payroll_check')
            except Exception:
                _logger.exception(
                    'Payroll check pull failed for company %s', config.company_id.name,
                )

    # ------------------------------------------------------------------
    # Archive upsert
    # ------------------------------------------------------------------

    def _upsert_checks(self, data, config):
        if 'qb.payroll.check' not in self.env:
            _logger.warning(
                "QuickBooks payroll archive model not loaded - skipping payroll "
                "check sync (install hr_payroll + hr_contract)"
            )
            return 0
        Check = self.env['qb.payroll.check'].sudo()
        post_journal = bool(getattr(config, 'qb_payroll_post_archive_journal', False))
        count = 0
        for payload in data.get('payrollChecks', []):
            qb_id = str(payload.get('id') or '')
            if not qb_id:
                continue
            employee = self._find_employee(payload.get('employeeId'))
            contract = self._latest_contract(employee, config) if employee else False
            vals = {
                'company_id': config.company_id.id,
                'qb_check_id': qb_id,
                'qb_employee_id': str(payload.get('employeeId') or ''),
                'employee_id': employee.id if employee else False,
                'contract_id': contract.id if contract else False,
                'display_name': payload.get('displayName') or qb_id,
                'check_number': payload.get('checkNumber') or False,
                'check_date': payload.get('checkDate') or False,
                'period_start': payload.get('payPeriodStart') or payload.get('checkDate') or False,
                'period_end': payload.get('payPeriodEnd') or payload.get('checkDate') or False,
                'payment_method': PAYMENT_METHOD_MAP.get(
                    str(payload.get('paymentMethod') or '').upper(),
                ),
                'status': STATUS_MAP.get(
                    str(payload.get('status') or 'PAID').upper(), 'other',
                ),
                'gross_pay': self._money(payload.get('grossPay')),
                'net_pay': self._money(payload.get('netPay')),
                'journal_ref_id': payload.get('journalRefId') or False,
                'qb_last_synced': fields.Datetime.now(),
                'qb_raw_json': payload,
                'ytd_json': payload.get('ytd') or False,
            }
            existing = Check.search([
                ('company_id', '=', config.company_id.id),
                ('qb_check_id', '=', qb_id),
            ], limit=1)
            if existing:
                existing.write(vals)
                check = existing
                check.line_ids.unlink()
            else:
                check = Check.create(vals)
            self._upsert_lines(check, payload)
            if post_journal:
                self._post_archive_journal(check, config)
            count += 1
        return count

    def _upsert_lines(self, check, payload):
        Line = self.env['qb.payroll.check.line'].sudo()
        sequence = 10
        for earning in payload.get('earnings') or []:
            Line.create(self._line_vals(
                check, earning, 'earning', sequence=sequence,
            ))
            sequence += 10
        for tax in payload.get('taxes') or []:
            employee_amt = self._money(tax.get('employee'))
            employer_amt = self._money(tax.get('employer'))
            fallback_amt = self._money(tax.get('amount'))
            if employee_amt:
                Line.create(self._line_vals(
                    check, tax, 'tax', amount=employee_amt,
                    is_employer_side=False, sequence=sequence,
                ))
                sequence += 10
            if employer_amt:
                Line.create(self._line_vals(
                    check, tax, 'tax', amount=employer_amt,
                    is_employer_side=True, sequence=sequence,
                ))
                sequence += 10
            if not employee_amt and not employer_amt and fallback_amt:
                Line.create(self._line_vals(
                    check, tax, 'tax', amount=fallback_amt,
                    is_employer_side=False, sequence=sequence,
                ))
                sequence += 10
        for deduction in payload.get('deductions') or []:
            employee_amt = self._money(deduction.get('employee'))
            employer_amt = self._money(deduction.get('employer'))
            fallback_amt = self._money(deduction.get('amount'))
            if employee_amt or (not employer_amt and fallback_amt):
                Line.create(self._line_vals(
                    check, deduction, 'deduction',
                    amount=employee_amt or fallback_amt,
                    is_employer_side=False, sequence=sequence,
                ))
                sequence += 10
            if employer_amt:
                Line.create(self._line_vals(
                    check, deduction, 'deduction', amount=employer_amt,
                    is_employer_side=True, sequence=sequence,
                ))
                sequence += 10
        for contrib in payload.get('employerContributions') or []:
            Line.create(self._line_vals(
                check, contrib, 'employer_contribution',
                is_employer_side=True, sequence=sequence,
            ))
            sequence += 10

    def _line_vals(self, check, payload, line_type, amount=None,
                   is_employer_side=False, sequence=10):
        salary_rule = self._match_salary_rule(
            payload.get('payItemId'), check.company_id,
        )
        vals = {
            'check_id': check.id,
            'sequence': sequence,
            'line_type': line_type,
            'is_employer_side': is_employer_side,
            'qb_pay_item_id': str(payload.get('payItemId') or '') or False,
            'salary_rule_id': salary_rule.id if salary_rule else False,
            'name': payload.get('name') or payload.get('type') or line_type.title(),
            'code': payload.get('code') or False,
            'qb_tax_type': payload.get('type') if line_type == 'tax' else False,
            'qb_tax_jurisdiction': payload.get('jurisdiction') if line_type == 'tax' else False,
            'hours': self._money(payload.get('hours')) if line_type == 'earning' else 0.0,
            'rate': self._money(payload.get('rate')) if line_type == 'earning' else 0.0,
            'amount': amount if amount is not None else self._money(payload.get('amount')),
            'is_pre_tax': bool(payload.get('isPreTax')),
            'qb_raw_json': payload,
        }
        return vals

    def _match_salary_rule(self, qb_pay_item_id, company):
        if not qb_pay_item_id or 'hr.salary.rule' not in self.env:
            return False
        Rule = self.env['hr.salary.rule'].sudo()
        if 'qb_pay_item_id' not in Rule._fields:
            return False
        return Rule.search([
            ('qb_pay_item_id', '=', str(qb_pay_item_id)),
        ], limit=1)

    def _find_employee(self, qb_employee_id):
        if not qb_employee_id or 'hr.employee' not in self.env:
            return False
        if 'qb_employee_id' not in self.env['hr.employee']._fields:
            return False
        return self.env['hr.employee'].sudo().search([
            ('qb_employee_id', '=', str(qb_employee_id)),
        ], limit=1)

    def _latest_contract(self, employee, config):
        if 'hr.contract' not in self.env:
            return False
        return self.env['hr.contract'].sudo().search([
            ('employee_id', '=', employee.id),
            ('company_id', '=', config.company_id.id),
        ], order='date_start desc, id desc', limit=1)

    @staticmethod
    def _money(value):
        if isinstance(value, dict):
            value = value.get('value') or value.get('amount')
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # Optional GL mirror
    # ------------------------------------------------------------------

    def _post_archive_journal(self, check, config):
        if not check or 'account.move' not in self.env:
            return False
        if check.archive_move_id:
            return check.archive_move_id
        company = check.company_id
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            _logger.warning(
                'No general journal available on %s; skipping archive journal entry for QB check %s',
                company.name, check.qb_check_id,
            )
            return False

        Move = self.env['account.move'].sudo()
        AccountAccount = self.env['account.account'].sudo()
        lines = []
        for line in check.line_ids:
            account = self._account_for_line(line, AccountAccount, company)
            if not account:
                continue
            credit = 0.0
            debit = 0.0
            amount = abs(line.amount or 0.0)
            if not amount:
                continue
            if line.line_type == 'earning':
                debit = amount
            elif line.line_type in ('tax', 'deduction'):
                credit = amount
            elif line.line_type == 'employer_contribution':
                debit = amount
            lines.append((0, 0, {
                'name': line.name or check.display_name or check.qb_check_id,
                'account_id': account.id,
                'debit': debit,
                'credit': credit,
                'partner_id': line.salary_rule_id.qb_vendor_id.id if line.salary_rule_id and line.salary_rule_id.qb_vendor_id else False,
            }))

        net = abs(check.net_pay or 0.0)
        if net:
            clearing = self._clearing_account(AccountAccount, company)
            if clearing:
                lines.append((0, 0, {
                    'name': 'Net Pay - %s' % (check.display_name or check.qb_check_id),
                    'account_id': clearing.id,
                    'debit': 0.0,
                    'credit': net,
                }))

        debit_total = sum(l[2]['debit'] for l in lines)
        credit_total = sum(l[2]['credit'] for l in lines)
        if not lines or round(debit_total - credit_total, 2) != 0.0:
            _logger.info(
                'Skipping archive journal for QB check %s: unbalanced (D=%.2f C=%.2f).',
                check.qb_check_id, debit_total, credit_total,
            )
            return False
        move = Move.create({
            'company_id': company.id,
            'journal_id': journal.id,
            'date': check.check_date or fields.Date.context_today(self),
            'ref': 'QB Payroll Check %s' % check.qb_check_id,
            'line_ids': lines,
        })
        check.archive_move_id = move.id
        return move

    def _account_for_line(self, line, AccountAccount, company):
        rule = line.salary_rule_id
        if rule:
            if line.line_type == 'earning' and rule.qb_gl_account_id:
                return rule.qb_gl_account_id
            if line.line_type in ('tax', 'deduction') and rule.qb_liability_account_id:
                return rule.qb_liability_account_id
            if line.line_type == 'employer_contribution' and rule.qb_gl_account_id:
                return rule.qb_gl_account_id
        return False

    def _clearing_account(self, AccountAccount, company):
        domain = [
            ('account_type', '=', 'liability_current'),
            ('name', 'ilike', 'payroll'),
        ]
        if 'company_ids' in AccountAccount._fields:
            domain.append(('company_ids', 'in', company.id))
        elif 'company_id' in AccountAccount._fields:
            domain.append(('company_id', '=', company.id))
        return AccountAccount.search(domain, limit=1)
