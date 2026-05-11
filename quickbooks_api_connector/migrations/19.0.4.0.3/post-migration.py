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
    """Re-clean stale QuickBooks deposit push jobs and pause the queue cron.

    The 19.0.4.0.2 migration was extended in-place to also reset ``failed``
    deposit push jobs after the version had already shipped. Databases that
    upgraded to 19.0.4.0.2 before that extension landed never saw the
    ``failed``-state cleanup, so they keep emailing operators and surfacing
    the original ``DepositToAccountRef`` / ``DepositLineDetail`` 400s in the
    queue list view.

    On top of that, when a deploy of the pre-fix branch keeps getting served
    after partial rollback (e.g. odoo.sh build failed and the platform falls
    back to the previous image), the runtime keeps spamming the same 400
    every two minutes through the ``QuickBooks: Process Sync Queue`` cron.
    To prevent that loop on databases that just managed to land a successful
    upgrade, this migration also flips the queue-processor cron inactive.

    The operator can re-enable the cron from Settings -> Technical ->
    Automation -> Scheduled Actions after confirming the runtime ``push``
    guard is live (commit 4232c85 / 4d61237 / 25e78c9).

    Implemented as raw SQL so the upgrade cannot fail for any ORM-related
    reason. Idempotent: re-running matches zero rows once cleanup is done.
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

    cr.execute(
        """
        UPDATE ir_cron
           SET active = false
         WHERE active = true
           AND id IN (
               SELECT res_id FROM ir_model_data
                WHERE module = 'quickbooks_api_connector'
                  AND model = 'ir.cron'
                  AND name = 'ir_cron_qb_queue_processor'
           )
        """
    )
    if cr.rowcount:
        _logger.info(
            'Paused the QuickBooks queue-processor cron during the '
            '19.0.4.0.3 upgrade. Re-enable it from Settings -> Technical '
            '-> Scheduled Actions once you have verified that the deposit '
            'push validation is active on the running image.'
        )
