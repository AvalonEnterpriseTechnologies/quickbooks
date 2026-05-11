import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Reclassify linked QBO retained earnings accounts to Odoo unaffected equity."""
    cr = env.cr
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'account_account' AND column_name = 'qb_account_subtype'"
    )
    if not cr.fetchone():
        return

    Account = env['account.account'].sudo()
    accounts = Account.search([
        ('qb_account_subtype', '=', 'RetainedEarnings'),
        ('account_type', '=', 'equity'),
        ('qb_account_id', '!=', False),
    ])
    if accounts:
        accounts.with_context(skip_qb_sync=True).write({
            'account_type': 'equity_unaffected',
        })
        _logger.info(
            'Reclassified %s QuickBooks retained earnings account(s).',
            len(accounts),
        )
