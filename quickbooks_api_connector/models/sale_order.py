from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    qb_estimate_id = fields.Char(string='QB Estimate ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_sync_error = fields.Text(string='Last Sync Error', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_qb_sync'):
            return res
        qb_fields = {
            'partner_id', 'date_order', 'validity_date', 'order_line',
            'currency_id', 'note',
        }
        if qb_fields & set(vals):
            for order in self.filtered(lambda r: not r.qb_do_not_sync):
                order._trigger_qb_estimate_sync('update')
        return res

    def action_confirm(self):
        res = super().action_confirm()
        if not self.env.context.get('skip_qb_sync'):
            for order in self.filtered(lambda r: not r.qb_do_not_sync):
                order._trigger_qb_estimate_sync('create')
        return res

    def _trigger_qb_estimate_sync(self, operation):
        self.ensure_one()
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type='estimate',
            direction='push',
            operation=operation,
            odoo_record_id=self.id,
            odoo_model='sale.order',
        )
