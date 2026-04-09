from . import models
from . import controllers
from . import wizards
from . import services


def _post_init_hook(env):
    """Grant QB groups to admin and optionally register with SLATE integration registry."""
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if not admin:
        return

    group_xmlids = [
        'quickbooks_api_module.group_qb_manager',
        'quickbooks_api_module.group_qb_user',
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
            technical_module='quickbooks_api_module',
            config_model='quickbooks.config',
            sync_log_model='quickbooks.sync.log',
        )
