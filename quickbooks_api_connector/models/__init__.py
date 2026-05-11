import inspect
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


# Map each optional model-extension file to the Odoo addon whose model it
# extends via ``_inherit``. Odoo 19's registry loader is strict: declaring
# ``_inherit = 'sale.order'`` when the ``sale`` addon is not installed
# raises ``TypeError: Model 'sale.order' does not exist in registry.`` and
# aborts the entire module load. We must only import these files when the
# parent addon will be present in the registry.
_OPTIONAL_MODEL_EXTENSIONS = (
    ('hr_employee', 'hr'),
    ('hr_department', 'hr'),
    ('hr_expense', 'hr_expense'),
    ('purchase_order', 'purchase'),
    ('project_project', 'project'),
    ('sale_order', 'sale'),
    ('stock_move', 'stock'),
    ('slate_bridge', 'slate_connector_v19'),
)

_INSTALLED_STATES = ('installed', 'to install', 'to upgrade', 'to remove')


def _find_loader_cursor():
    """Return the database cursor used by Odoo's module loader, if any.

    When Odoo imports this package during ``Registry.new(dbname, ...)``,
    the loader keeps the cursor in a local named ``cr`` on its stack
    frames (``load_modules`` / ``load_module_graph``). Walking back from
    here lets us reuse that cursor to probe ``ir_module_module`` without
    opening a second connection on the same database.
    """
    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame is not None else None
        while frame is not None:
            candidate = frame.f_locals.get('cr')
            if candidate is not None and hasattr(candidate, 'execute') \
                    and hasattr(candidate, 'fetchone'):
                return candidate
            frame = frame.f_back
    finally:
        del frame
    return None


def _addon_will_be_loaded(cr, addon_name):
    """Return True if ``addon_name`` is (or is being) installed.

    States ``installed``, ``to install`` and ``to upgrade`` all mean the
    addon's models will exist in the registry by the time inheritance is
    resolved. ``to remove`` is included because the module is still
    present in the current registry build until the removal is committed.
    """
    if cr is None:
        return False
    try:
        cr.execute(
            "SELECT state FROM ir_module_module WHERE name = %s",
            (addon_name,),
        )
        row = cr.fetchone()
    except Exception:
        _logger.debug(
            'Could not probe ir_module_module for %s; treating as absent.',
            addon_name, exc_info=True,
        )
        return False
    return bool(row) and row[0] in _INSTALLED_STATES


def _safe_import(module_name):
    """Import an optional model extension, logging but swallowing failures."""
    try:
        __import__(__name__ + '.' + module_name)
    except Exception:  # pragma: no cover - defensive
        _logger.exception(
            'Failed to import optional model extension %s; the related '
            'QuickBooks features will be disabled.', module_name,
        )


_loader_cursor = _find_loader_cursor()

for _module_file, _parent_addon in _OPTIONAL_MODEL_EXTENSIONS:
    if _addon_will_be_loaded(_loader_cursor, _parent_addon):
        _safe_import(_module_file)
    else:
        _logger.info(
            'Skipping QuickBooks model extension %s; addon %r is not '
            'installed in this database.', _module_file, _parent_addon,
        )
