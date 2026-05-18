"""Backfill native Odoo payslips from QuickBooks Online paychecks.

``qb.sync.payroll.checks`` already archives every QBO paycheck into the
read-only ``qb.payroll.check`` table so the original payload is preserved
forever. This service is the second half: it takes those archived checks
and projects them into native Odoo ``hr.payslip`` rows grouped under
``hr.payslip.run`` batches, posted as ``done`` so they look like
historical pay runs.

Design notes
------------

* The bridge addon ``quickbooks_api_connector_hr_payroll`` adds
  ``qb_check_id`` to ``hr.payslip`` and ``qb_payslip_run_id`` to
  ``hr.payslip.run``. Both are unique per company, so re-running the
  backfill is idempotent: existing rows are updated in place, missing
  rows are created.
* Batches are keyed by ``(period_start, period_end)`` of the QBO
  paycheck. When period fields are missing we fall back to the check
  date so every imported row still lands in some batch.
* We never call ``hr.payslip.compute_sheet`` against the imported rows
  because the salary rules required to recompute QBO checks aren't
  always present in Odoo. Instead we write the totals directly and flip
  the state to ``done`` so the rows are read-only.
* All side-effecting writes use ``skip_qb_sync=True`` to avoid bouncing
  back through the queue.
"""

import logging
from collections import defaultdict
from datetime import date

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayrollPayslips(models.AbstractModel):
    _name = 'qb.sync.payroll.payslips'
    _description = 'QuickBooks Payroll → hr.payslip Backfill'

    # ------------------------------------------------------------------
    # Orchestrator entry points (mirror every other payroll service)
    # ------------------------------------------------------------------

    def push(self, client, config, job):
        _logger.info('Payslip backfill is read-only; nothing to push to QBO.')
        return {}

    def push_all(self, client, config, entity_type):
        _logger.info('Payslip backfill is read-only; nothing to push to QBO.')

    def pull(self, client, config, job):
        return self.pull_all(client, config, job.entity_type)

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return 0
        if not getattr(config, 'sync_payroll_payslips', True):
            return 0
        return self._backfill(config)

    def cron_pull_for_all_companies(self):
        configs = self.env['quickbooks.config'].search([
            ('state', '=', 'connected'),
            ('payroll_enabled', '=', True),
        ])
        for config in configs:
            try:
                self.pull_all(None, config, 'payroll_payslip')
            except Exception:
                _logger.exception(
                    'Payslip backfill failed for company %s', config.company_id.name,
                )

    # ------------------------------------------------------------------
    # Backfill core
    # ------------------------------------------------------------------

    def _backfill(self, config):
        if (
            'hr.payslip' not in self.env
            or 'hr.payslip.run' not in self.env
            or 'qb.payroll.check' not in self.env
        ):
            _logger.warning(
                'Payslip backfill skipped: hr_payroll bridge not installed '
                '(missing hr.payslip / hr.payslip.run / qb.payroll.check).'
            )
            return 0
        Payslip = self.env['hr.payslip'].sudo()
        if 'qb_check_id' not in Payslip._fields:
            _logger.warning(
                'Payslip backfill skipped: quickbooks_api_connector_hr_payroll '
                'bridge fields are not loaded.'
            )
            return 0

        Check = self.env['qb.payroll.check'].sudo()
        checks = Check.search([
            ('company_id', '=', config.company_id.id),
            ('employee_id', '!=', False),
        ], order='period_end, period_start, check_date, id')
        if not checks:
            _logger.info(
                'Payslip backfill: no qb.payroll.check rows for company %s; '
                'nothing to do (run "Sync Payroll Checks" first).',
                config.company_id.name,
            )
            return 0

        batches = self._group_by_period(checks)
        created_runs = 0
        upserted_payslips = 0
        for batch_key, batch_checks in batches.items():
            try:
                with self.env.cr.savepoint():
                    run = self._ensure_batch(config, batch_key, batch_checks)
                    if not run:
                        continue
                    for check in batch_checks:
                        if self._upsert_payslip(config, run, check):
                            upserted_payslips += 1
                    created_runs += 1
            except Exception:
                _logger.exception(
                    'Payslip backfill: batch %s failed for company %s '
                    '(savepoint rolled back).',
                    batch_key, config.company_id.name,
                )

        _logger.info(
            'Payslip backfill: processed %d batch(es), upserted %d payslip(s) for %s.',
            created_runs, upserted_payslips, config.company_id.name,
        )
        return upserted_payslips

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------

    def _group_by_period(self, checks):
        buckets = defaultdict(list)
        for check in checks:
            period_start = check.period_start or check.check_date or date.today()
            period_end = check.period_end or check.check_date or period_start
            key = (period_start, period_end)
            buckets[key].append(check)
        return dict(sorted(buckets.items()))

    def _ensure_batch(self, config, batch_key, checks):
        Run = self.env['hr.payslip.run'].sudo()
        period_start, period_end = batch_key
        qb_key = 'qbo:%s:%s' % (period_start.isoformat(), period_end.isoformat())
        domain = [
            ('company_id', '=', config.company_id.id),
            ('qb_payslip_run_id', '=', qb_key),
        ]
        run = Run.search(domain, limit=1)
        vals = {
            'company_id': config.company_id.id,
            'qb_payslip_run_id': qb_key,
            'date_start': period_start,
            'date_end': period_end,
            'qb_last_synced': fields.Datetime.now(),
        }
        if 'name' in Run._fields:
            vals['name'] = 'QBO Pay Run %s → %s' % (
                period_start.isoformat(), period_end.isoformat(),
            )
        if run:
            run.with_context(skip_qb_sync=True).write(vals)
        else:
            run = Run.with_context(skip_qb_sync=True).create(vals)
        return run

    # ------------------------------------------------------------------
    # Payslip upsert
    # ------------------------------------------------------------------

    def _upsert_payslip(self, config, run, check):
        Payslip = self.env['hr.payslip'].sudo()
        if not check.employee_id:
            _logger.info(
                'Payslip backfill: skipping QBO check %s (no matched employee). '
                'Run dedupe / re-pull payroll employees and retry.',
                check.qb_check_id,
            )
            return False
        domain = [
            ('company_id', '=', config.company_id.id),
            ('qb_check_id', '=', check.qb_check_id),
        ]
        payslip = Payslip.with_context(active_test=False).search(domain, limit=1)
        vals = {
            'company_id': config.company_id.id,
            'employee_id': check.employee_id.id,
            'contract_id': check.contract_id.id if check.contract_id else False,
            'payslip_run_id': run.id,
            'date_from': check.period_start or check.check_date,
            'date_to': check.period_end or check.check_date,
            'qb_check_id': check.qb_check_id,
            'qb_employee_id': check.qb_employee_id or False,
            'qb_gross_pay': check.gross_pay or 0.0,
            'qb_net_pay': check.net_pay or 0.0,
            'qb_status': check.status or 'paid',
            'qb_last_synced': fields.Datetime.now(),
            'qb_raw_json': check.qb_raw_json or False,
        }
        if 'name' in Payslip._fields:
            vals['name'] = check.display_name or (
                'QBO Paycheck %s' % check.qb_check_id
            )
        if 'number' in Payslip._fields and check.check_number:
            vals['number'] = check.check_number
        if 'struct_id' in Payslip._fields and check.contract_id and check.contract_id.structure_type_id:
            default_struct = check.contract_id.structure_type_id.default_struct_id
            if default_struct:
                vals['struct_id'] = default_struct.id
        vals = {k: v for k, v in vals.items() if k in Payslip._fields}

        if payslip:
            payslip.with_context(skip_qb_sync=True).write(vals)
        else:
            payslip = Payslip.with_context(skip_qb_sync=True).create(vals)

        # Best-effort: mark posted/done so the row is read-only and shows up
        # as a historical pay run. We do NOT call compute_sheet because the
        # salary rules used by QBO are not represented in Odoo and would
        # zero out the gross/net we just wrote.
        if 'state' in payslip._fields and payslip.state != 'done':
            try:
                payslip.with_context(skip_qb_sync=True).write({'state': 'done'})
            except Exception:
                _logger.exception(
                    'Payslip backfill: could not flip payslip %s (QBO check %s) '
                    'to done; left in state %s.',
                    payslip.id, check.qb_check_id, payslip.state,
                )

        return True
