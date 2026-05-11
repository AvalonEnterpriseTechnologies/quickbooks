import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Backfill Phase 0 metadata for existing connected companies."""
    configs = env['quickbooks.config'].search([('state', '=', 'connected')])
    auth_service = env['qb.auth.service']
    probe_service = env['qb.data.probe']
    company_info = env['qb.sync.company.info']

    for config in configs:
        vals = {}
        if not getattr(config, 'granted_scopes', False):
            vals['granted_scopes'] = auth_service._get_scopes(config)
        if vals:
            config.write(vals)

        try:
            client = env['qb.api.client'].get_client(config)
            company_info.pull_all(client, config, 'company_info')
        except Exception:
            _logger.exception(
                'Failed to backfill QuickBooks subscription data for %s',
                config.company_id.display_name,
            )

        try:
            probe_service.run_all(config)
        except Exception:
            _logger.exception(
                'Failed to run QuickBooks data probes for %s',
                config.company_id.display_name,
            )
