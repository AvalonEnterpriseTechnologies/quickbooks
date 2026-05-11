import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Backfill QBO account links with the functional CoA matcher."""
    configs = env['quickbooks.config'].search([('state', '=', 'connected')])
    matcher = env['qb.record.matcher']
    account_service = env['qb.sync.accounts']

    for config in configs:
        try:
            client = env['qb.api.client'].get_client(config)
            accounts = client.query_all('Account', where_clause='')
        except Exception:
            _logger.exception(
                'Could not fetch QBO accounts for CoA relink migration in %s.',
                config.company_id.display_name,
            )
            continue

        for qb_data in accounts:
            existing, decision = matcher.find_odoo_match_for_account(
                qb_data, config.company_id, return_reason=True,
            )
            if not existing:
                continue
            vals = account_service._qb_account_to_odoo(qb_data)
            matcher.link_odoo_record(existing, 'account', qb_data)
            existing.with_context(skip_qb_sync=True).write(
                account_service._existing_account_update_vals(existing, vals, config),
            )
            env['quickbooks.account.reconciliation'].sudo().record_decision(
                config=config,
                qb_data=qb_data,
                account=existing,
                decision=decision,
            )

        try:
            env['qb.sync.journals'].ensure_journals_for_accounts(config)
        except Exception:
            _logger.exception(
                'Could not ensure QBO journals during CoA relink migration in %s.',
                config.company_id.display_name,
            )
