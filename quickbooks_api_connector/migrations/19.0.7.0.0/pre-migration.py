"""Drop the legacy payroll-checks cron before 19.0.7.0.0 rewires it.

The 19.0.7.0.0 release replaces ``ir_cron_qb_payroll_checks`` with the
broader ``ir_cron_qb_payroll_full`` cron driven by the new
``qb.sync.payroll.orchestrator`` model. Dropping the old ``ir.model.data``
row up front prevents Odoo from leaving a dangling reference when the
data file is reloaded under the new name.
"""

import logging

_logger = logging.getLogger(__name__)

LEGACY_XMLIDS = (
    'ir_cron_qb_payroll_checks',
)


def migrate(env, version):
    if not version:
        return
    cr = env.cr
    for xmlid in LEGACY_XMLIDS:
        ref = env.ref(
            'quickbooks_api_connector.%s' % xmlid,
            raise_if_not_found=False,
        )
        if ref:
            try:
                ref.sudo().unlink()
            except Exception:
                _logger.exception(
                    'Could not unlink legacy cron %s; will only drop the '
                    'ir_model_data row.',
                    xmlid,
                )
        cr.execute(
            "DELETE FROM ir_model_data WHERE module=%s AND name=%s",
            ('quickbooks_api_connector', xmlid),
        )
