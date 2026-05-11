import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    """Restore queue processing after the defensive 19.0.4.0.3 pause."""
    cr = env.cr
    cr.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'quickbooks_sync_queue'"
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        UPDATE ir_cron
           SET active = true
         WHERE id IN (
               SELECT res_id FROM ir_model_data
                WHERE module = 'quickbooks_api_connector'
                  AND model = 'ir.cron'
                  AND name = 'ir_cron_qb_queue_processor'
           )
           AND EXISTS (
               SELECT 1 FROM quickbooks_config
                WHERE state = 'connected'
           )
        """
    )
    if cr.rowcount:
        _logger.info('Re-enabled QuickBooks queue processor cron.')

    cr.execute(
        """
        UPDATE quickbooks_sync_queue
           SET state = 'pending',
               next_retry_at = NULL,
               error_message = COALESCE(error_message, '') ||
                   E'\nReset by 19.0.4.1.1 queue restore migration.'
         WHERE state = 'processing'
        """
    )
    if cr.rowcount:
        _logger.info(
            'Reset %s orphaned QuickBooks processing jobs to pending.',
            cr.rowcount,
        )
