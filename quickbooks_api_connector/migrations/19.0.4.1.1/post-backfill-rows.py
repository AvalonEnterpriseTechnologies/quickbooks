import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Populate hierarchical report rows for snapshots imported pre-19.0.4.1.1."""
    cr = env.cr
    cr.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'quickbooks_report_snapshot'"
    )
    if not cr.fetchone():
        return

    snapshots = env['quickbooks.report.snapshot'].sudo().search([
        ('raw_json', '!=', False),
    ])
    report_service = env['qb.sync.reports'].sudo()
    count = 0
    for snapshot in snapshots:
        config = env['quickbooks.config'].sudo().search([
            ('company_id', '=', snapshot.company_id.id),
        ], limit=1)
        if not config:
            continue
        report_service._store_report_rows(config, snapshot, snapshot.raw_json or {})
        count += 1
    if count:
        _logger.info(
            'Backfilled hierarchical QuickBooks report rows for %s snapshots.',
            count,
        )
