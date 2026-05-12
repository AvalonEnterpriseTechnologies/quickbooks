"""Drop legacy QuickBooks UI artifacts before the 19.0.6.0.0 upgrade.

19.0.6.0.0 reduces the connector to a single custom ``ir.ui.view`` (the
Settings panel block) and replaces every other dedicated menu/list/form
with a native Odoo surface (chatter, ``mail.activity``, server-action
``Action`` bindings, computed fields on ``res.config.settings``).

This pre-migration sweeps the now-orphaned ``ir.model.data`` rows so the
standard Odoo upgrade does not leave dangling references to deleted
external IDs, menus, actions, or views.
"""

import logging

_logger = logging.getLogger(__name__)

LEGACY_XMLIDS = (
    # Custom forms / lists / searches
    'view_quickbooks_config_form',
    'view_quickbooks_config_list',
    'action_quickbooks_config',
    'view_quickbooks_sync_log_list',
    'view_quickbooks_sync_log_form',
    'view_quickbooks_sync_log_search',
    'action_quickbooks_sync_log',
    'action_quickbooks_reconciliation_report',
    'view_quickbooks_sync_queue_list',
    'view_quickbooks_sync_queue_form',
    'view_quickbooks_sync_queue_search',
    'action_quickbooks_sync_queue',
    'view_quickbooks_coverage_matrix_list',
    'view_quickbooks_dashboard_form',
    'action_quickbooks_coverage_matrix',
    'action_quickbooks_dashboard',
    'view_qb_balance_variance_list',
    'view_qb_balance_variance_form',
    'action_qb_balance_variances',
    # Native model form inherits
    'view_partner_form_qb',
    'view_product_form_qb',
    'view_account_account_form_qb',
    'view_account_move_form_qb',
    'view_account_analytic_line_form_qb',
    # Wizard views + actions that have been retired
    'view_quickbooks_setup_wizard_form',
    'action_quickbooks_setup_wizard',
    'view_quickbooks_sync_wizard_form',
    'action_quickbooks_sync_wizard',
    'view_quickbooks_migration_wizard_form',
    'action_quickbooks_migration_wizard',
    # Menu tree under Settings > Technical > QuickBooks
    'menu_qb_technical_root',
    'menu_quickbooks_sync_panel',
    'menu_quickbooks_sync_log',
    'menu_quickbooks_dashboard',
    'menu_quickbooks_sync_queue',
    'menu_quickbooks_reconciliation_report',
    'menu_quickbooks_coverage_matrix',
    'menu_qb_balance_variances',
    'menu_quickbooks_config',
    'action_quickbooks_open_or_setup',
    # OAuth result QWeb template (replaced by a redirect to /odoo/settings)
    'qb_oauth_result_template',
    # Mail template that used to email failed-job notifications. Permanent
    # failures now raise a native mail.activity on the affected record.
    'mail_template_sync_failure',
)


def migrate(env, version):
    """Delete every legacy ir.model.data row for the listed XMLIDs."""
    if not version:
        return
    cr = env.cr

    for xmlid in LEGACY_XMLIDS:
        try:
            ref = env.ref(
                'quickbooks_api_connector.%s' % xmlid,
                raise_if_not_found=False,
            )
            if ref:
                try:
                    ref.sudo().unlink()
                except Exception:
                    _logger.exception(
                        'Could not unlink legacy QB record %s; will only '
                        'drop ir_model_data row',
                        xmlid,
                    )
        finally:
            cr.execute(
                "DELETE FROM ir_model_data WHERE module=%s AND name=%s",
                ('quickbooks_api_connector', xmlid),
            )

    # The dropped TransientModel/Model classes leave their underlying
    # ir.model + table entries behind. Schedule them for removal so a
    # subsequent registry update finishes the cleanup.
    obsolete_models = (
        'quickbooks.dashboard',
        'quickbooks.sync.wizard',
        'quickbooks.setup.wizard',
    )
    for model_name in obsolete_models:
        cr.execute(
            "SELECT id FROM ir_model WHERE model = %s",
            (model_name,),
        )
        row = cr.fetchone()
        if not row:
            continue
        ir_model = env['ir.model'].browse(row[0])
        try:
            ir_model.sudo().unlink()
        except Exception:
            _logger.exception(
                'Could not drop ir_model row for %s; manual cleanup may be '
                'required',
                model_name,
            )
