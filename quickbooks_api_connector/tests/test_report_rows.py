from .common import QuickbooksTestCommon


class TestReportRows(QuickbooksTestCommon):

    def test_report_row_hierarchy_walk(self):
        snapshot = self.env['quickbooks.report.snapshot'].create({
            'company_id': self.company.id,
            'report_type': 'BalanceSheet',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'accounting_method': 'Accrual',
            'schema_version': 'v1',
            'raw_json': {},
            'row_count': 0,
        })
        payload = {
            'Rows': {
                'Row': [{
                    'Header': {'ColData': [{'value': 'Assets'}]},
                    'Rows': {
                        'Row': [{
                            'ColData': [
                                {'value': 'Checking', 'id': '10'},
                                {'value': '100.00'},
                            ],
                        }],
                    },
                    'Summary': {'ColData': [
                        {'value': 'Total Assets'},
                        {'value': '100.00'},
                    ]},
                }],
            },
        }

        self.env['qb.sync.reports']._store_report_rows(
            self.config, snapshot, payload,
        )

        rows = self.env['quickbooks.report.row'].search([
            ('snapshot_id', '=', snapshot.id),
        ], order='sequence')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].label, 'Assets')
        self.assertTrue(rows[0].is_section)
        self.assertEqual(rows[1].parent_id, rows[0])
        self.assertEqual(rows[1].level, 1)
        self.assertEqual(rows[2].label, 'Total Assets')
        self.assertTrue(rows[2].is_total)
