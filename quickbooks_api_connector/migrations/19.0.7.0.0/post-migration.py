"""Migrate legacy hr.payslip QuickBooks rows into qb.payroll.check.

Versions of the connector prior to 19.0.7.0.0 wrote QuickBooks payroll
checks as half-populated ``hr.payslip`` rows (no struct_id, no contract_id,
no salary lines). Those rows could never be computed or posted, so the
connector now writes a dedicated ``qb.payroll.check`` archive instead.

This post-migration:

1. Copies every legacy ``hr.payslip`` row that has ``qb_check_id`` set into
   the new ``qb.payroll.check`` table (one row per check, keyed on
   company_id + qb_check_id).
2. Re-parents any payslip-input rows that carried ``qb_source_check_id`` /
   ``qb_employee_id`` onto a matching ``qb.payroll.check.line`` of type
   ``benefit`` so the deduction / benefit detail is preserved.
3. Unlinks the original ``hr.payslip`` rows so Odoo's payroll workflow
   does not list them as broken draft payslips after the upgrade.

The script is idempotent: re-running it does not double-create archive
rows, and it silently skips when the bridge models are absent (the
connector ships standalone in addons paths without ``hr_payroll``).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    if not version:
        return
    if 'hr.payslip' not in env or 'qb.payroll.check' not in env:
        _logger.info(
            '19.0.7.0.0 post-migration skipped: hr.payslip / qb.payroll.check '
            'not available in this database.'
        )
        return

    Payslip = env['hr.payslip'].sudo()
    Check = env['qb.payroll.check'].sudo()
    Line = env['qb.payroll.check.line'].sudo()

    if 'qb_check_id' not in Payslip._fields:
        _logger.info(
            '19.0.7.0.0 post-migration skipped: legacy hr.payslip.qb_check_id '
            'field not present.'
        )
        return

    legacy = Payslip.search([
        ('qb_check_id', '!=', False),
    ])
    if not legacy:
        _logger.info('19.0.7.0.0 post-migration: no legacy QB payslips to migrate.')
        return

    migrated = 0
    for payslip in legacy:
        qb_check_id = payslip.qb_check_id
        if not qb_check_id:
            continue
        existing_check = Check.search([
            ('company_id', '=', payslip.company_id.id),
            ('qb_check_id', '=', qb_check_id),
        ], limit=1)
        if existing_check:
            check = existing_check
        else:
            check_vals = {
                'company_id': payslip.company_id.id,
                'qb_check_id': qb_check_id,
                'qb_employee_id': payslip.qb_employee_id or False,
                'employee_id': payslip.employee_id.id if payslip.employee_id else False,
                'contract_id': (
                    payslip.contract_id.id
                    if 'contract_id' in payslip._fields and payslip.contract_id
                    else False
                ),
                'display_name': payslip.name or qb_check_id,
                'check_date': (
                    payslip.date_to or payslip.date_from or False
                ),
                'period_start': payslip.date_from or False,
                'period_end': payslip.date_to or False,
                'gross_pay': float(getattr(payslip, 'qb_gross_pay', 0.0) or 0.0),
                'net_pay': float(getattr(payslip, 'qb_net_pay', 0.0) or 0.0),
                'status': payslip.qb_status or 'paid',
                'qb_raw_json': getattr(payslip, 'qb_raw_json', False) or {},
            }
            check = Check.create(check_vals)

        if 'hr.payslip.input' in env:
            PayslipInput = env['hr.payslip.input'].sudo()
            if 'qb_source_check_id' in PayslipInput._fields:
                inputs = PayslipInput.search([
                    ('qb_source_check_id', '=', qb_check_id),
                ])
                for inp in inputs:
                    Line.create({
                        'check_id': check.id,
                        'line_type': 'benefit',
                        'is_employer_side': False,
                        'qb_pay_item_id': False,
                        'name': inp.name or 'Migrated benefit',
                        'code': (inp.code or inp.name or '')[:64] or False,
                        'amount': float(inp.amount or 0.0),
                        'qb_benefit_type': getattr(inp, 'qb_benefit_type', False),
                        'qb_raw_json': getattr(inp, 'qb_raw_json', False) or {},
                    })
                inputs.unlink()

        try:
            payslip.unlink()
        except Exception:
            _logger.exception(
                'Could not unlink legacy QB payslip %s; manual cleanup required.',
                payslip.id,
            )
            continue
        migrated += 1

    _logger.info(
        '19.0.7.0.0 post-migration: archived %d legacy QuickBooks payslips into '
        'qb.payroll.check.',
        migrated,
    )
