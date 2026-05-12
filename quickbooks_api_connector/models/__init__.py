from . import quickbooks_config
from . import quickbooks_settings
from . import quickbooks_sync_log
from . import quickbooks_sync_queue
from . import quickbooks_field_mapping
from . import quickbooks_data_probe
from . import quickbooks_migration_run
from . import quickbooks_coverage_matrix
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
from . import account_reconcile_model
from . import ir_model_fields
from . import qb_balance_variance

# Optional Odoo addons (sale, hr, hr_expense, purchase, project, stock,
# slate_connector_v19) are integrated through dedicated bridge modules
# (``quickbooks_api_connector_<addon>``). Each bridge declares ``depends``
# on this connector and the optional addon, and uses ``auto_install=True``,
# so Odoo installs the bridge automatically whenever both sides are
# present. This is the standard Odoo idiom for cross-module integrations
# and guarantees correct registry load order.
