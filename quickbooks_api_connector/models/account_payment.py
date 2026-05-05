import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    qb_payment_id = fields.Char(
        string='QB Payment ID', index=True, copy=False,
    )
    qb_billpayment_id = fields.Char(
        string='QB Bill Payment ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_sync_error = fields.Text(string='Last Sync Error', copy=False)
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False,
    )

    def action_post(self):
        res = super().action_post()
        if not self.env.context.get('skip_qb_sync'):
            for payment in self.filtered(lambda p: not p.qb_do_not_sync):
                payment._trigger_qb_sync('create')
        return res

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_qb_sync'):
            return res
        qb_fields = {
            'amount', 'date', 'partner_id', 'journal_id', 'payment_method_line_id',
            'memo', 'ref', 'currency_id',
        }
        if qb_fields & set(vals):
            for payment in self.filtered(
                lambda p: not p.qb_do_not_sync and p.state == 'posted'
            ):
                payment._trigger_qb_sync('update')
        return res

    def _trigger_qb_sync(self, operation):
        self.ensure_one()
        if self.partner_type == 'customer':
            entity_type = 'payment'
        elif self.partner_type == 'supplier':
            entity_type = 'bill_payment'
        else:
            return
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type=entity_type,
            direction='push',
            operation=operation,
            odoo_record_id=self.id,
            odoo_model='account.payment',
        )

    def action_sync_to_qb(self):
        for rec in self:
            rec._trigger_qb_sync('update')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': 'Payment sync queued.',
                'type': 'info',
                'sticky': False,
            },
        }
