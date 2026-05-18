"""Backfill the new sync_payroll_payslips toggle on existing configs.

19.0.11.0.0 introduces the qb.sync.payroll.payslips service and the
quickbooks.config.sync_payroll_payslips toggle (default=True). Odoo's
``_init_column`` populates the default for existing rows automatically
during the upgrade, but we set the value here explicitly so the upgrade
is idempotent across edge cases where the column was added via raw SQL.

The migration is intentionally NOT a one-shot trigger of the payslip
backfill itself — that can be heavy on large installs and is reserved
for the operator-driven "Enable QuickBooks Payroll (All Features)"
button + the daily orchestrator cron.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    if not version:
        return
    if 'quickbooks.config' not in env:
        return
    env.cr.execute(
        """
        UPDATE quickbooks_config
           SET sync_payroll_payslips = TRUE
         WHERE sync_payroll_payslips IS NULL
        """
    )
    touched = env.cr.rowcount
    _logger.info(
        '19.0.11.0.0 post-migration: defaulted sync_payroll_payslips to '
        'True on %d existing QuickBooks config row(s).',
        touched,
    )
