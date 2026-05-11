import logging

from . import quickbooks_config
from . import quickbooks_settings
from . import quickbooks_sync_log
from . import quickbooks_sync_queue
from . import quickbooks_field_mapping
from . import quickbooks_data_probe
from . import quickbooks_report_snapshot
from . import quickbooks_account_reconciliation
from . import quickbooks_recurring_template
from . import quickbooks_custom_field_definition
from . import quickbooks_employee_benefit
from . import quickbooks_workers_comp_class
from . import quickbooks_hr_advisor_note
from . import quickbooks_payroll_settings
from . import quickbooks_bank_rule
from . import quickbooks_migration_run
from . import quickbooks_coverage_matrix
from . import quickbooks_dashboard
from . import quickbooks_payroll_compensation
from . import quickbooks_payroll_employee
from . import quickbooks_payroll_pay_item
from . import quickbooks_payroll_pay_schedule
from . import quickbooks_payroll_check
from . import quickbooks_work_location
from . import res_partner
from . import product_product
from . import account_account
from . import account_journal
from . import account_move
from . import account_payment
from . import account_tax
from . import account_analytic_account
from . import account_analytic_line
from . import account_payment_term
from . import ir_attachment

_logger = logging.getLogger(__name__)


def _safe_import(module_name):
    """Import an optional model extension.

    The module file is always imported. Odoo only registers ``_inherit``
    declarations whose parent model is actually present in the registry, so
    importing a file that extends e.g. ``sale.order`` is harmless when the
    ``sale`` addon is not installed. We catch any import error here so that
    a single misconfigured optional dependency never prevents this addon
    from loading.
    """
    try:
        __import__(__name__ + '.' + module_name)
    except Exception:  # pragma: no cover - defensive
        _logger.exception(
            'Failed to import optional model extension %s; the related '
            'QuickBooks features will be disabled.', module_name,
        )


# Optional model extensions: import unconditionally so the fields are
# registered whenever the corresponding optional Odoo modules are
# installed alongside this addon. Previous releases gated these imports
# on ``sys.modules``, but that test races against Odoo's module loader
# (our addon does not depend on these modules) and silently dropped the
# extensions, causing "Invalid field" errors at runtime.
for _optional_module in (
    'hr_employee',
    'hr_department',
    'hr_expense',
    'purchase_order',
    'project_project',
    'sale_order',
    'stock_move',
    'slate_bridge',
):
    _safe_import(_optional_module)
