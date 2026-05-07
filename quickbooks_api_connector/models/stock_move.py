from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    qb_inventory_adjustment_id = fields.Char(
        string='QB Inventory Adjustment ID', index=True, copy=False,
    )
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        moves._enqueue_qb_inventory_adjustments()
        return moves

    def _enqueue_qb_inventory_adjustments(self):
        queue = self.env['quickbooks.sync.queue'].sudo()
        configs = {
            config.company_id.id: config
            for config in self.env['quickbooks.config'].sudo().search([
                ('state', '=', 'connected'),
                ('sync_inventory_adjustments', '=', True),
            ])
        }
        for move in self:
            config = configs.get(move.company_id.id)
            if not config or move.qb_inventory_adjustment_id:
                continue
            product = move.product_id
            if not product or not getattr(product, 'qb_item_id', False):
                continue
            if not move._is_qb_inventory_adjustment_candidate():
                continue
            queue.enqueue(
                entity_type='inventory_adjustment',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='stock.move',
                company=move.company_id,
                idempotency_key='stock_move_%s_qb_inventory_adjustment' % move.id,
            )

    def _is_qb_inventory_adjustment_candidate(self):
        self.ensure_one()
        source_usage = self.location_id.usage if self.location_id else ''
        dest_usage = self.location_dest_id.usage if self.location_dest_id else ''
        return 'inventory' in (source_usage, dest_usage) or source_usage != dest_usage
