import logging

_logger = logging.getLogger(__name__)

ERROR_MESSAGE = (
    'Skipped during upgrade: deposit push jobs queued before the '
    '19.0.4.0.3 hardening could not build a valid QBO Deposit '
    'payload (missing DepositToAccountRef or DepositLineDetail). '
    'Re-enqueue manually if you still want any of these deposits '
    'pushed; otherwise the runtime push will continue to skip them.'
)


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

    Implemented as a single raw SQL ``UPDATE`` so the upgrade cannot fail for
    any ORM-related reason (computed-field recompute, mail tracking, audit
    trail materialization, constraint validation on unaffected fields, etc.).
    Stored compute fields on the queue model (e.g. ``display_name_computed``)
    will be lazily refreshed by Odoo on next read.

    Idempotent: re-running it on a clean database matches zero rows.
    """
    cr = env.cr
    cr.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'quickbooks_sync_queue'"
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE quickbooks_sync_queue
           SET state = 'done',
               next_retry_at = NULL,
               error_message = %s
         WHERE entity_type = 'deposit'
           AND direction = 'push'
           AND state IN ('pending', 'processing', 'conflict', 'failed')
        """,
        (ERROR_MESSAGE,),
    )
    if cr.rowcount:
        _logger.info(
            'Cleared %s stale QuickBooks deposit push jobs '
            '(states: pending/processing/conflict/failed) during 19.0.4.0.3 '
            'upgrade.',
            cr.rowcount,
        )
