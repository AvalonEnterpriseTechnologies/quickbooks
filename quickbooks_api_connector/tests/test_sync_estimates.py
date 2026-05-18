"""Estimate pull-side coverage tests.

Validates that the rewritten ``qb.sync.estimates._qb_estimate_to_odoo``
handles every QBO line-detail type (item / discount / shipping /
subtotal / note / group), persists DocNumber on the Odoo SO, and stamps
``qb_line_id`` so the relinker can reconstruct Estimate-line ->
Invoice-line connections.
"""

import unittest

from .common import QuickbooksTestCommon


class TestSyncEstimates(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'sale.order' not in cls.env:
            raise unittest.SkipTest('sale module not installed')
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Estimate Customer',
            'customer_rank': 1,
            'qb_customer_id': '6500',
        })
        cls.product = cls.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'Estimate Product',
            'list_price': 50.0,
            'qb_item_id': '6300',
        })

    def _estimate_payload(self, lines):
        return {
            'Id': '1100',
            'SyncToken': '0',
            'DocNumber': 'EST-1100',
            'CustomerRef': {'value': self.customer.qb_customer_id},
            'TxnDate': '2026-01-15',
            'ExpirationDate': '2026-02-15',
            'TotalAmt': sum(l.get('Amount', 0) for l in lines),
            'Line': lines,
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }

    def test_estimate_with_all_line_types(self):
        lines = [
            {
                'Id': '1',
                'DetailType': 'SalesItemLineDetail',
                'Amount': 100.0,
                'Description': 'Widget',
                'SalesItemLineDetail': {
                    'Qty': 2, 'UnitPrice': 50.0,
                    'ItemRef': {'value': self.product.qb_item_id},
                },
            },
            {
                'Id': '2',
                'DetailType': 'DescriptionOnly',
                'Description': 'Free-form note from QBO',
            },
            {
                'Id': '3',
                'DetailType': 'SubTotalLineDetail',
                'Amount': 100.0,
            },
            {
                'Id': '4',
                'DetailType': 'DiscountLineDetail',
                'Amount': 10.0,
                'DiscountLineDetail': {
                    'PercentBased': True, 'DiscountPercent': 10.0,
                },
            },
            {
                'Id': '5',
                'DetailType': 'ShippingLineDetail',
                'Amount': 15.0,
                'Description': 'Ground shipping',
            },
        ]

        self.env['qb.sync.estimates']._apply_pull(
            self._estimate_payload(lines), self.config,
        )
        order = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1100')], limit=1,
        )
        self.assertTrue(order)
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.qb_doc_number, 'EST-1100')
        self.assertEqual(order.client_order_ref, 'EST-1100')

        kinds = {line.qb_line_id: line for line in order.order_line}
        # Every QBO line Id must round-trip to qb_line_id on Odoo.
        self.assertEqual(
            set(kinds.keys()), {'1', '2', '3', '4', '5'},
        )

        # Item line uses the resolved product.
        self.assertEqual(kinds['1'].product_id, self.product)
        self.assertEqual(kinds['1'].product_uom_qty, 2)
        self.assertEqual(kinds['1'].price_unit, 50.0)

        # Note line is a display_type='line_note'.
        self.assertEqual(kinds['2'].display_type, 'line_note')
        self.assertIn('Free-form note', kinds['2'].name)

        # Subtotal becomes a line_section marker.
        self.assertEqual(kinds['3'].display_type, 'line_section')

        # Discount becomes a service-product line with negative price.
        self.assertTrue(kinds['4'].product_id)
        self.assertEqual(kinds['4'].product_id.default_code, 'QB_DISCOUNT')
        self.assertLess(kinds['4'].price_unit, 0)

        # Shipping becomes a service-product line with positive price.
        self.assertTrue(kinds['5'].product_id)
        self.assertEqual(kinds['5'].product_id.default_code, 'QB_SHIPPING')
        self.assertEqual(kinds['5'].price_unit, 15.0)

    def test_estimate_group_lines_are_expanded(self):
        lines = [{
            'Id': '7',
            'DetailType': 'GroupLineDetail',
            'GroupLineDetail': {
                'Quantity': 1,
                'Line': [
                    {
                        'Id': '7-1',
                        'DetailType': 'SalesItemLineDetail',
                        'Amount': 50.0,
                        'Description': 'Sub item',
                        'SalesItemLineDetail': {
                            'Qty': 1, 'UnitPrice': 50.0,
                            'ItemRef': {'value': self.product.qb_item_id},
                        },
                    },
                ],
            },
        }]
        self.env['qb.sync.estimates']._apply_pull(
            self._estimate_payload(lines), self.config,
        )
        order = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1100')], limit=1,
        )
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.qb_line_id, '7-1')

    def test_pull_is_idempotent_on_re_run(self):
        lines = [{
            'Id': '8',
            'DetailType': 'SalesItemLineDetail',
            'Amount': 200.0,
            'Description': 'Widget',
            'SalesItemLineDetail': {
                'Qty': 4, 'UnitPrice': 50.0,
                'ItemRef': {'value': self.product.qb_item_id},
            },
        }]
        payload = self._estimate_payload(lines)
        self.env['qb.sync.estimates']._apply_pull(payload, self.config)
        self.env['qb.sync.estimates']._apply_pull(payload, self.config)
        orders = self.env['sale.order'].search(
            [('qb_estimate_id', '=', '1100')],
        )
        self.assertEqual(len(orders), 1, 'Pulling the same Estimate twice must not duplicate')
