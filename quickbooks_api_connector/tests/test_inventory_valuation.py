from .common import QuickbooksTestCommon


class TestInventoryValuation(QuickbooksTestCommon):

    def test_inventory_valuation_rows_store_product_value(self):
        product = self.env['product.product'].create({
            'name': 'Valued Widget',
            'type': 'product',
            'qb_item_id': 'ITEM1',
        })
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'InventoryValuationSummary',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 1,
        })

        self.env['qb.sync.reports']._store_inventory_balances(
            self.config, snapshot, [{
                'id': 'ITEM1',
                'label': 'Valued Widget',
                'columns': [
                    {'value': 'Valued Widget', 'id': 'ITEM1'},
                    {'value': '4'},
                    {'value': '12.50'},
                    {'value': '50.00'},
                ],
            }],
        )

        balance = self.env['quickbooks.inventory.balance'].search([
            ('snapshot_id', '=', snapshot.id),
        ], limit=1)
        self.assertEqual(balance.product_id, product)
        self.assertEqual(balance.qty_on_hand, 4.0)
        self.assertEqual(balance.avg_cost, 12.5)
        self.assertEqual(balance.value, 50.0)

