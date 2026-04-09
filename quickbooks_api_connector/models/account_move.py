import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MOVE_TYPE_MAP = {
    'out_invoice': 'invoice',
    'in_invoice': 'bill',
    'out_refund': 'credit_memo',
    'entry': 'journal_entry',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    qb_invoice_id = fields.Char(
        string='QB Invoice ID', index=True, copy=False,
    )
    qb_bill_id = fields.Char(
        string='QB Bill ID', index=True, copy=False,
    )
    qb_creditmemo_id = fields.Char(
        string='QB Credit Memo ID', index=True, copy=False,
    )
    qb_je_id = fields.Char(
        string='QB Journal Entry ID', index=True, copy=False,
    )
    qb_salesreceipt_id = fields.Char(
        string='QB Sales Receipt ID', index=True, copy=False,
    )
    qb_deposit_id = fields.Char(
        string='QB Deposit ID', index=True, copy=False,
    )
    qb_transfer_id = fields.Char(
        string='QB Transfer ID', index=True, copy=False,
    )
    qb_refundreceipt_id = fields.Char(
        string='QB Refund Receipt ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_sync_error = fields.Text(string='Last Sync Error', copy=False)
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False,
    )

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
