import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MOVE_TYPE_MAP = {
    'out_invoice': 'invoice',
    'in_invoice': 'bill',
    'out_refund': 'credit_memo',
    'in_refund': 'vendor_credit',
    'entry': 'journal_entry',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    qb_invoice_id = fields.Char(
        string='QB Invoice ID', index=True, copy=False, tracking=True,
    )
    qb_bill_id = fields.Char(
        string='QB Bill ID', index=True, copy=False, tracking=True,
    )
    qb_creditmemo_id = fields.Char(
        string='QB Credit Memo ID', index=True, copy=False, tracking=True,
    )
    qb_je_id = fields.Char(
        string='QB Journal Entry ID', index=True, copy=False, tracking=True,
    )
    qb_salesreceipt_id = fields.Char(
        string='QB Sales Receipt ID', index=True, copy=False, tracking=True,
    )
    qb_deposit_id = fields.Char(
        string='QB Deposit ID', index=True, copy=False, tracking=True,
    )
    qb_transfer_id = fields.Char(
        string='QB Transfer ID', index=True, copy=False, tracking=True,
    )
    qb_refundreceipt_id = fields.Char(
        string='QB Refund Receipt ID', index=True, copy=False, tracking=True,
    )
    qb_vendorcredit_id = fields.Char(
        string='QB Vendor Credit ID', index=True, copy=False, tracking=True,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
    qb_sync_error = fields.Text(
        string='Last Sync Error', copy=False, tracking=True,
    )
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False, tracking=True,
    )
    qb_opening_snapshot_id = fields.Integer(
        string='Legacy QB Opening Snapshot ID',
        copy=False,
        index=True,
    )
    qb_exchange_rate = fields.Float(
        string='QB Exchange Rate',
        copy=False,
        digits=(16, 8),
    )
    qb_home_total_amt = fields.Monetary(
        string='QB Home Total Amount',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_recurring_id = fields.Char(
        string='QB Recurring Transaction ID', index=True, copy=False,
    )
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        if not self.env.context.get('skip_qb_sync'):
            for move in posted.filtered(lambda m: not m.qb_do_not_sync):
                move._trigger_qb_sync('create')
        return posted

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_qb_sync'):
            for move in self.filtered(
                lambda m: m.state == 'posted' and not m.qb_do_not_sync
            ):
                move._trigger_qb_sync('update')
        return res

    def _trigger_qb_sync(self, operation):
        self.ensure_one()
        entity_type = MOVE_TYPE_MAP.get(self.move_type)
        if not entity_type:
            return
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type=entity_type,
            direction='push',
            operation=operation,
            odoo_record_id=self.id,
            odoo_model='account.move',
        )

    def action_sync_to_qb(self):
        for rec in self:
            rec._trigger_qb_sync('update')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': 'Move sync queued.',
                'type': 'info',
                'sticky': False,
            },
        }

    def action_qb_push_transfer(self):
        """Manual: enqueue this journal entry as a QBO Transfer push.

        Validates that both line accounts have ``qb_account_id`` set
        before enqueueing. Refuses with a clear UserError when either is
        missing, so we never produce the empty-FromAccountRef / empty-
        ToAccountRef payload that QBO rejects with validation error 2020.
        """
        Queue = self.env['quickbooks.sync.queue']
        Config = self.env['quickbooks.config']
        for move in self:
            if move.move_type != 'entry':
                raise UserError(_(
                    'Only journal entries (move_type=entry) can be '
                    'pushed as a QuickBooks Transfer. %s is %s.'
                ) % (move.display_name, move.move_type))

            debit_line = move.line_ids.filtered(lambda l: l.debit > 0)[:1]
            credit_line = move.line_ids.filtered(lambda l: l.credit > 0)[:1]
            missing = []
            if (
                not credit_line
                or not credit_line.account_id
                or not getattr(credit_line.account_id, 'qb_account_id', False)
            ):
                missing.append(_('source bank account (FromAccountRef)'))
            if (
                not debit_line
                or not debit_line.account_id
                or not getattr(debit_line.account_id, 'qb_account_id', False)
            ):
                missing.append(_('destination bank account (ToAccountRef)'))
            if missing:
                raise UserError(_(
                    'Cannot push %s to QuickBooks: missing %s. Open '
                    'Settings > QuickBooks, run "Apply QBO Account '
                    'Mapping", then retry.'
                ) % (move.display_name, ', '.join(missing)))

            config = Config.search(
                [('company_id', '=', move.company_id.id)], limit=1,
            )
            if not config:
                raise UserError(_(
                    'QuickBooks is not configured for company %s.'
                ) % move.company_id.display_name)
            if config.state != 'connected':
                raise UserError(_(
                    'QuickBooks is not connected for company %s.'
                ) % move.company_id.display_name)

            Queue.enqueue(
                entity_type='transfer',
                direction='push',
                operation='update' if move.qb_transfer_id else 'create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=move.company_id,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('QuickBooks Transfer Push'),
                'message': _('Queued %d transfer push job(s).') % len(self),
                'type': 'success',
                'sticky': False,
            },
        }
