from unittest import SkipTest
from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncInventoryAdjustments(QuickbooksTestCommon):

    def setUp(self):
        super().setUp()
        if 'stock.move' not in self.env:
            raise SkipTest('stock module is not installed')

    def test_push_inventory_adjustment_creates_item_adjustment(self):
        product = self.env['product.product'].create({
            'name': 'Stocked Item',
            'type': 'product',
            'qb_item_id': '300',
            'standard_price': 5.0,
        })
        inventory_location = self.env['stock.location'].create({
            'name': 'Inventory Adjustment',
            'usage': 'inventory',
        })
        stock_location = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
        ], limit=1)
        move = self.env['stock.move'].create({
            'name': 'Adjustment',
            'product_id': product.id,
            'product_uom_qty': 3.0,
            'product_uom': product.uom_id.id,
            'location_id': inventory_location.id,
            'location_dest_id': stock_location.id,
            'company_id': self.company.id,
        })
        client = self._mock_client()
        client.create.return_value = {'ItemAdjustment': {'Id': 'IA1'}}
        job = MagicMock(odoo_record_id=move.id)

        result = self.env['qb.sync.inventory.adjustments'].push(
            client, self.config, job,
        )

        self.assertEqual(result['qb_id'], 'IA1')
        self.assertEqual(move.qb_inventory_adjustment_id, 'IA1')
        client.create.assert_called_once()
