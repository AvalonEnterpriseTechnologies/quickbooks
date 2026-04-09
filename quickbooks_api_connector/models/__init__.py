from . import quickbooks_config
from . import quickbooks_settings
from . import quickbooks_sync_log
from . import quickbooks_sync_queue
from . import quickbooks_field_mapping
from . import res_partner
from . import product_product
from . import account_account
from . import account_move
from . import account_payment
from . import account_tax
from . import account_analytic_account
from . import account_analytic_line
from . import account_payment_term

# Optional: hr (employees, departments)
try:
    import odoo.addons.hr  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
else:
    from . import hr_employee
    from . import hr_department

# Optional: hr_expense
try:
    import odoo.addons.hr_expense  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
else:
    from . import hr_expense

# Optional: purchase
try:
    import odoo.addons.purchase  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
else:
    from . import purchase_order

# Optional: slate_connector_v19
try:
    import odoo.addons.slate_connector_v19  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
else:
    from . import slate_bridge
