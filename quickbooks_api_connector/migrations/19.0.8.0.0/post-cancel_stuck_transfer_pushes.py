"""Cancel every queued Transfer push job that pre-dates the manual-only flip.

Until 19.0.8.0.0 the connector auto-enqueued an Odoo->QBO Transfer push
job for every transfer-shaped account.move that lacked qb_transfer_id.
When the Odoo bank account did not yet have qb_account_id set, the push
service produced a payload with empty FromAccountRef / ToAccountRef and
Intuit rejected the request with validation error 2020. The queue then
re-tried the job, which produced the same failure forever; the cron
fired every minute and burnt API quota for no work.

The qb_auto_push_transfers toggle (default OFF) on quickbooks.config
turns off the auto-enqueue, and the manual action_qb_push_transfer on
account.move now validates the payload before enqueueing. This script
purges the backlog so the cron stops hammering Intuit immediately after
the upgrade.

The script is idempotent: re-running it does nothing if the rows are
already cancelled.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    if not version:
        return
    if 'quickbooks.sync.queue' not in env:
        return

    env.cr.execute(
        """
        UPDATE quickbooks_sync_queue
           SET state = 'done',
               error_message = COALESCE(error_message, '') || E'\\n' ||
                   'Cancelled by 19.0.8.0.0 migration: Transfer pushes are '
                   'now manual only. Use the "Push Transfer to QuickBooks" '
                   'action on the journal entry when ready.'
         WHERE entity_type = 'transfer'
           AND direction = 'push'
           AND state IN ('pending', 'processing', 'failed')
        """,
    )
    cancelled = env.cr.rowcount
    _logger.info(
        '19.0.8.0.0 post-migration: cancelled %d stuck QuickBooks Transfer '
        'push job(s). The cron will no longer retry them.',
        cancelled,
    )
