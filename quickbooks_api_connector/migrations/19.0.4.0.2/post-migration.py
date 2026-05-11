import logging

_logger = logging.getLogger(__name__)

ERROR_MESSAGE = (
    'Skipped during upgrade: deposit push jobs queued by older '
    'connector versions could not build a valid QBO Deposit payload '
    '(missing DepositToAccountRef or DepositLineDetail). Re-enqueue '
    'manually if you still want any of these deposits pushed.'
)


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

    Implemented as a single raw SQL ``UPDATE`` so the upgrade cannot fail for
    any ORM-related reason (computed-field recompute, mail tracking, audit
    trail materialization, constraint validation on unaffected fields, etc.).
    Stored compute fields on the queue model (e.g. ``display_name_computed``)
    will be lazily refreshed by Odoo on next read.
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
            'Skipped %s stale QuickBooks deposit push jobs '
            '(states: pending/processing/conflict/failed).',
            cr.rowcount,
        )
