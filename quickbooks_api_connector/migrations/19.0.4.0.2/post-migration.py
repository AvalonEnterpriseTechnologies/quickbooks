import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Stop old invalid deposit push jobs from retrying after upgrade.

    Versions before 19.0.4.0.2 could queue deposit pushes for journal entries
    that did not have enough QBO account mapping to build DepositToAccountRef
    and DepositLineDetail. The runtime service now skips those safely; this
    migration cleans up any already-queued jobs from the old code path so that
    the QuickBooks cron stops re-attempting payloads that QBO will always
    reject with a 400 ValidationFault.

    We also reset jobs that already drained their retry budget into the
    ``failed`` state, since they were created from the same broken payload
    builder and would never succeed on a retry.
    """
    queue = env['quickbooks.sync.queue'].sudo()
    stale_states = ('pending', 'processing', 'conflict', 'failed')
    jobs = queue.search([
        ('entity_type', '=', 'deposit'),
        ('direction', '=', 'push'),
        ('state', 'in', stale_states),
    ])
    if not jobs:
        return
    jobs.write({
        'state': 'done',
        'next_retry_at': False,
        'error_message': (
            'Skipped during upgrade: deposit push jobs queued by older '
            'connector versions could not build a valid QBO Deposit payload '
            '(missing DepositToAccountRef or DepositLineDetail). Re-enqueue '
            'manually if you still want any of these deposits pushed.'
        ),
    })
    _logger.info(
        'Skipped %s stale QuickBooks deposit push jobs '
        '(states: pending/processing/conflict/failed).',
        len(jobs),
    )
