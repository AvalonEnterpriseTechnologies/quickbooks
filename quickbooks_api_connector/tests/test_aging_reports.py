from .common import QuickbooksTestCommon


class TestAgingReports(QuickbooksTestCommon):

    def test_aged_receivables_store_customer_buckets(self):
        partner = self.env['res.partner'].create({
            'name': 'Aging Customer',
            'customer_rank': 1,
            'qb_customer_id': 'CUST1',
        })
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'AgedReceivables',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 1,
        })
        rows = [{
            'id': 'CUST1',
            'label': 'Aging Customer',
            'columns': [
                {'value': 'Aging Customer', 'id': 'CUST1'},
                {'value': '10.00'},
                {'value': '20.00'},
                {'value': '30.00'},
                {'value': '40.00'},
                {'value': '50.00'},
                {'value': '150.00'},
            ],
        }]

        self.env['qb.sync.reports']._store_partner_balances(
            self.config, snapshot, 'AgedReceivables', rows,
        )

        balance = self.env['quickbooks.partner.balance'].search([
            ('snapshot_id', '=', snapshot.id),
        ], limit=1)
        self.assertEqual(balance.partner_id, partner)
        self.assertEqual(balance.kind, 'customer')
        self.assertEqual(balance.bucket_current, 10.0)
        self.assertEqual(balance.bucket_1_30, 20.0)
        self.assertEqual(balance.bucket_over_90, 50.0)
        self.assertEqual(balance.total, 150.0)

