import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Stop old invalid deposit push jobs from retrying after upgrade.

    Versions before 19.0.4.0.2 could queue deposit pushes for journal entries
    that did not have enough QBO account mapping to build DepositToAccountRef
    and DepositLineDetail. The runtime service now skips those safely; this
    migration cleans up any already-queued jobs from the old code path.
    """
    queue = env['quickbooks.sync.queue'].sudo()
    jobs = queue.search([
        ('entity_type', '=', 'deposit'),
        ('direction', '=', 'push'),
        ('state', 'in', ('pending', 'processing', 'conflict')),
    ])
    if not jobs:
        return
    jobs.write({
        'state': 'done',
        'error_message': (
            'Skipped during upgrade: deposit push jobs queued by older connector '
            'versions may be missing QBO DepositToAccountRef or DepositLineDetail.'
        ),
    })
    _logger.info('Skipped %s stale QuickBooks deposit push jobs.', len(jobs))
