from .common import QuickbooksTestCommon


class TestRecordMatcher(QuickbooksTestCommon):

    def test_find_odoo_match_by_qb_id_first(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Existing Customer',
            'email': 'different@example.com',
            'customer_rank': 1,
            'qb_customer_id': '1000',
        })
        qb_data = {
            'Id': '1000',
            'DisplayName': 'Other Name',
            'PrimaryEmailAddr': {'Address': 'test@example.com'},
        }

        match = self.env['qb.record.matcher'].find_odoo_match(
            'customer', qb_data, self.company,
        )

        self.assertEqual(match, partner)

    def test_find_odoo_match_by_email_when_unlinked(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Email Match',
            'email': 'email-match@example.com',
            'customer_rank': 1,
        })
        qb_data = {
            'Id': '1001',
            'DisplayName': 'Different Name',
            'PrimaryEmailAddr': {'Address': 'email-match@example.com'},
        }

        match = self.env['qb.record.matcher'].find_odoo_match(
            'customer', qb_data, self.company,
        )

        self.assertEqual(match, partner)

    def test_find_odoo_match_by_product_sku(self):
        product = self.env['product.product'].with_context(skip_qb_sync=True).create({
            'name': 'SKU Match',
            'default_code': 'SKU-100',
            'type': 'consu',
        })
        qb_data = {'Id': '2001', 'Name': 'Different', 'Sku': 'SKU-100'}

        match = self.env['qb.record.matcher'].find_odoo_match(
            'product', qb_data, self.company,
        )

        self.assertEqual(match, product)

    def test_find_qbo_match_queries_stable_key(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'QBO Match',
            'customer_rank': 1,
        })
        client = self._mock_client()
        client.query.return_value = {
            'QueryResponse': {
                'Customer': [{'Id': '3001', 'SyncToken': '2', 'DisplayName': 'QBO Match'}],
            },
        }

        match = self.env['qb.record.matcher'].find_qbo_match(client, 'customer', partner)

        self.assertEqual(match['Id'], '3001')
        self.assertIn('DisplayName', client.query.call_args[0][0])
