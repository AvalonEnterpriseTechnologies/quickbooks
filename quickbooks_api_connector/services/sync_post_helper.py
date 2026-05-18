import logging

from odoo import models

_logger = logging.getLogger(__name__)


class QBSyncPostHelper(models.AbstractModel):
    """Shared helper for posting freshly pulled QBO transactional records.

    QBO transactions (Invoice, Bill, VendorCredit, JournalEntry, Payment,
    BillPayment) are always posted on the QuickBooks side. The connector's
    pull services create the matching Odoo records in `draft` state by
    default, which forces operators to hand-post every imported record
    during a migration and blocks downstream reconciliation.

    Every transactional sync service calls ``post(record, config)`` after
    creating (or QBO-wins overwriting) a record. The helper is a no-op
    unless ``config.auto_post_pulled_records`` is True and the record is
    actually in ``draft`` state. Failures during posting are captured to
    ``qb_sync_error`` on the record so the rest of the sync continues;
    they do NOT propagate as exceptions.
    """

    _name = 'qb.sync.post.helper'
    _description = 'QuickBooks Pulled Record Auto-Post Helper'

    def post(self, record, config):
        """Post ``record`` if config allows and it is still draft.

        Returns True when a post call ran successfully, False otherwise.
        Never raises: exceptions are logged and captured to
        ``qb_sync_error`` so caller flows are not interrupted.
        """
        if not record or not record.exists():
            return False
        if not getattr(config, 'auto_post_pulled_records', True):
            return False
        if not hasattr(record, 'state') or record.state != 'draft':
            return False
        if not hasattr(record, 'action_post'):
            return False
        try:
            record.with_context(skip_qb_sync=True).action_post()
        except Exception as exc:
            _logger.warning(
                'Auto-post failed for %s id=%s: %s',
                record._name, record.id, exc,
            )
            if 'qb_sync_error' in record._fields:
                try:
                    record.with_context(skip_qb_sync=True).write({
                        'qb_sync_error': 'Auto-post failed: %s' % exc,
                    })
                except Exception:
                    _logger.exception(
                        'Failed to record qb_sync_error on %s id=%s',
                        record._name, record.id,
                    )
            return False
        return True
