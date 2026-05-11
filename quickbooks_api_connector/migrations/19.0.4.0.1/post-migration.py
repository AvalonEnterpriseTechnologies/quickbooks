import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Install the Accountant app on upgrades when the Enterprise addon exists."""
    module = env['ir.module.module'].sudo().search(
        [('name', '=', 'account_accountant')],
        limit=1,
    )
    if not module:
        _logger.warning(
            'account_accountant is not available in this Odoo environment; '
            'skipping automatic Accountant app installation.'
        )
        return
    if module.state in ('installed', 'to install', 'to upgrade'):
        return
    module.button_immediate_install()
