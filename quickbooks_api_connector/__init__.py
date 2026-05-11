from odoo.exceptions import UserError

from . import models
from . import controllers
from . import wizards
from . import services


REQUIRED_MODULES = ('account',)
OPTIONAL_AUTO_INSTALL_MODULES = ('account_accountant',)


def _ensure_required_modules_installed(env):
    """Hard-fail the install if a required Odoo module is not actually installed.

    The manifest already lists these modules in `depends`, which makes Odoo's
    module loader install them as part of the dependency graph. This runtime
    check is a belt-and-braces guard for unusual installation paths (manual
    database surgery, broken upgrades, partial restores) where a dependency
    could end up in a state other than `installed` while this module initializes.
    """
    Module = env['ir.module.module'].sudo()
    missing = []
    for tech_name in REQUIRED_MODULES:
        record = Module.search([('name', '=', tech_name)], limit=1)
        if not record or record.state != 'installed':
            missing.append(tech_name)
    if missing:
        raise UserError(
            "QuickBooks API Connector requires the following Odoo module(s) "
            "to be installed first: %s. Install them from Apps and then "
            "retry installing the QuickBooks connector." % ", ".join(missing)
        )


def _install_available_accountant_modules(env):
    """Install the Enterprise Accountant app when it exists in this database.

    `account_accountant` is an Enterprise addon and may be absent from staging
    builds that only have Community addons in their addons path. Keeping it out
    of manifest dependencies avoids a registry load failure in that case, while
    still forcing the app to install automatically for Enterprise databases.
    """
    Module = env['ir.module.module'].sudo()
    for tech_name in OPTIONAL_AUTO_INSTALL_MODULES:
        record = Module.search([('name', '=', tech_name)], limit=1)
        if record and record.state not in ('installed', 'to install', 'to upgrade'):
            record.button_immediate_install()


def _post_init_hook(env):
    """Grant QB groups to admin and optionally register with SLATE integration registry."""
    _ensure_required_modules_installed(env)
    _install_available_accountant_modules(env)

    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if not admin:
        return

    group_xmlids = [
        'quickbooks_api_connector.group_qb_manager',
        'quickbooks_api_connector.group_qb_user',
    ]
    for xmlid in group_xmlids:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            env.cr.execute(
                "INSERT INTO res_groups_users_rel (gid, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (group.id, admin.id),
            )

    from .compat import get_integration_registry
    registry = get_integration_registry(env)
    if registry is not None:
        registry.register_provider(
            provider='quickbooks',
            technical_module='quickbooks_api_connector',
            config_model='quickbooks.config',
            sync_log_model='quickbooks.sync.log',
        )

    env.cr.execute(
        """
        UPDATE quickbooks_config
           SET conflict_resolution = 'odoo_wins'
         WHERE conflict_resolution IS NULL
        """
    )
