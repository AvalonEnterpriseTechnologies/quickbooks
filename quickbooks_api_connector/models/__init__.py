from . import quickbooks_config
from . import quickbooks_sync_log
from . import quickbooks_sync_queue
from . import quickbooks_field_mapping
from . import res_partner
from . import product_product
from . import account_account
from . import account_move
from . import account_payment
from . import account_tax

try:
    import odoo.addons.slate_connector_v19  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pass
else:
    from . import slate_bridge
