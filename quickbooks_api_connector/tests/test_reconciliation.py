from .common import QuickbooksTestCommon


class TestReconciliation(QuickbooksTestCommon):

    def test_reconciliation_classifies_qbo_only_and_odoo_only(self):
        self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Missing In QBO',
            'customer_rank': 1,
            'qb_customer_id': '9001',
        })
        client = self._mock_client()
        client.query_all.return_value = [{
            'Id': '9002',
            'SyncToken': '0',
            'DisplayName': 'Missing In Odoo',
            'PrimaryEmailAddr': {'Address': 'missing@example.com'},
        }]

        result = self.env['qb.reconciliation']._reconcile_entity(
            client,
            self.config,
            'customer',
            self.env['qb.record.matcher'].get_meta('customer'),
        )

        self.assertEqual(result['qbo_only'], ['9002'])
        self.assertTrue(result['odoo_only'])
        pull_job = self.env['quickbooks.sync.queue'].search([
            ('entity_type', '=', 'customer'),
            ('direction', '=', 'pull'),
            ('qb_entity_id', '=', '9002'),
        ], limit=1)
        self.assertTrue(pull_job)

    def test_reconciliation_auto_links_high_confidence_match(self):
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Auto Link',
            'email': 'auto-link@example.com',
            'customer_rank': 1,
        })
        client = self._mock_client()
        client.query_all.return_value = [{
            'Id': '9003',
            'SyncToken': '0',
            'DisplayName': 'QBO Auto Link',
            'PrimaryEmailAddr': {'Address': 'auto-link@example.com'},
        }]

        self.env['qb.reconciliation']._reconcile_entity(
            client,
            self.config,
            'customer',
            self.env['qb.record.matcher'].get_meta('customer'),
        )

        partner.invalidate_recordset()
        self.assertEqual(partner.qb_customer_id, '9003')
