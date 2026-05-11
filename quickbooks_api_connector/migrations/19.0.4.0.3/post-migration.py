import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Re-clean stale QuickBooks deposit push jobs after the 19.0.4.0.2 hot-fix.

    The 19.0.4.0.2 migration was extended in-place to also reset ``failed``
    deposit push jobs after the version had already shipped. Databases that
    upgraded to 19.0.4.0.2 before that extension landed never saw the
    ``failed``-state cleanup, so they keep emailing operators and surfacing
    the original ``DepositToAccountRef`` / ``DepositLineDetail`` 400s in the
    queue list view.

    The runtime ``sync_deposits.push`` now validates the payload and short
    circuits to ``{'skipped': True}`` before calling QBO, so the queue can no
    longer regress to this state on its own. This migration just unsticks any
    rows that were already in the queue from before the runtime fix shipped.

    Idempotent: re-running it on a clean database is a no-op because every
    eligible row will already be in the ``done`` state.
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
            'Skipped during upgrade: deposit push jobs queued before the '
            '19.0.4.0.3 hardening could not build a valid QBO Deposit '
            'payload (missing DepositToAccountRef or DepositLineDetail). '
            'Re-enqueue manually if you still want any of these deposits '
            'pushed; otherwise the runtime push will continue to skip them.'
        ),
    })
    _logger.info(
        'Cleared %s stale QuickBooks deposit push jobs '
        '(states: pending/processing/conflict/failed) during 19.0.4.0.3 '
        'upgrade.',
        len(jobs),
    )
