import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncInventoryAdjustments(models.AbstractModel):
    _name = 'qb.sync.inventory.adjustments'
    _description = 'QuickBooks Inventory Adjustment Sync'

    def push(self, client, config, job):
        if 'stock.move' not in self.env:
            return {}
        move = self.env['stock.move'].browse(job.odoo_record_id)
        if not move.exists() or move.qb_inventory_adjustment_id:
            return {}
        payload = self._stock_move_to_qb_adjustment(move, config)
        if not payload:
            return {}
        resp = client.create('ItemAdjustment', payload)
        adjustment = resp.get('ItemAdjustment', {})
        qb_id = str(adjustment.get('Id') or '')
        move.with_context(skip_qb_sync=True).write({
            'qb_inventory_adjustment_id': qb_id,
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': qb_id}

    def pull(self, client, config, job):
        _logger.info('Skipping inventory adjustment pull; stock moves remain Odoo-led.')
        return {}

    def pull_all(self, client, config, entity_type):
        _logger.info('Skipping inventory adjustment pull_all; stock moves remain Odoo-led.')

    def push_all(self, client, config, entity_type):
        if 'stock.move' not in self.env:
            return
        moves = self.env['stock.move'].search([
            ('state', '=', 'done'),
            ('qb_inventory_adjustment_id', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        for move in moves.filtered(lambda m: m.product_id.qb_item_id):
            if move._is_qb_inventory_adjustment_candidate():
                self.env['quickbooks.sync.queue'].enqueue(
                    entity_type='inventory_adjustment',
                    direction='push',
                    operation='create',
                    odoo_record_id=move.id,
                    odoo_model='stock.move',
                    company=config.company_id,
                    idempotency_key='stock_move_%s_qb_inventory_adjustment' % move.id,
                )

    def _stock_move_to_qb_adjustment(self, move, config):
        product = move.product_id
        if not product or not product.qb_item_id:
            return {}
        qty_delta = self._quantity_delta(move)
        if not qty_delta:
            return {}
        line = {
            'DetailType': 'ItemAdjustmentLineDetail',
            'Amount': abs(qty_delta) * (product.standard_price or 0.0),
            'Description': move.reference or move.name or '',
            'ItemAdjustmentLineDetail': {
                'ItemRef': {'value': product.qb_item_id, 'name': product.name},
                'QtyDiff': qty_delta,
            },
        }
        account_ref = self._inventory_adjustment_account(product, config)
        if account_ref:
            line['ItemAdjustmentLineDetail']['AccountRef'] = {'value': account_ref}
        return {
            'TxnDate': (move.date or fields.Date.today()).date().isoformat()
            if hasattr(move.date, 'date') else fields.Date.today().isoformat(),
            'PrivateNote': 'Odoo stock move %s' % (move.reference or move.name or move.id),
            'Line': [line],
        }

    def _quantity_delta(self, move):
        qty = getattr(move, 'quantity_done', False) or getattr(move, 'quantity', 0.0)
        source_usage = move.location_id.usage if move.location_id else ''
        dest_usage = move.location_dest_id.usage if move.location_dest_id else ''
        if source_usage == 'inventory' and dest_usage != 'inventory':
            return qty
        if dest_usage == 'inventory' and source_usage != 'inventory':
            return -qty
        if dest_usage in ('internal', 'transit') and source_usage not in ('internal', 'transit'):
            return qty
        if source_usage in ('internal', 'transit') and dest_usage not in ('internal', 'transit'):
            return -qty
        return 0.0

    def _inventory_adjustment_account(self, product, config):
        if not getattr(config, 'sync_inventory_valuation_accounts', False):
            return None
        categ = product.categ_id
        account = (
            categ.property_stock_valuation_account_id
            or categ.property_stock_account_input_categ_id
            or categ.property_stock_account_output_categ_id
        )
        return account.qb_account_id if account and account.qb_account_id else None
