import sys

from . import quickbooks_config
from . import quickbooks_settings
from . import quickbooks_sync_log
from . import quickbooks_sync_queue
from . import quickbooks_field_mapping
from . import quickbooks_payroll_compensation
from . import quickbooks_payroll_employee
from . import quickbooks_payroll_pay_item
from . import quickbooks_payroll_pay_schedule
from . import quickbooks_payroll_check
from . import quickbooks_work_location
from . import res_partner
from . import product_product
from . import account_account
from . import account_move
from . import account_payment
from . import account_tax
from . import account_analytic_account
from . import account_analytic_line
from . import account_payment_term

# Extend models from optional modules only when Odoo has loaded them
# (checking sys.modules instead of import, because on Odoo.sh all addon
# packages exist on disk regardless of installation state)

if 'odoo.addons.hr' in sys.modules:
    from . import hr_employee
    from . import hr_department

if 'odoo.addons.hr_expense' in sys.modules:
    from . import hr_expense

if 'odoo.addons.purchase' in sys.modules:
    from . import purchase_order

if 'odoo.addons.project' in sys.modules:
    from . import project_project

if 'odoo.addons.sale' in sys.modules:
    from . import sale_order

if 'odoo.addons.stock' in sys.modules:
    from . import stock_move

if 'odoo.addons.slate_connector_v19' in sys.modules:
    from . import slate_bridge
