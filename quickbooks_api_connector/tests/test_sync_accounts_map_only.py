from .common import QuickbooksTestCommon


class TestSyncAccountsMapOnly(QuickbooksTestCommon):
    """Verify that account_strategy gates whether unmatched QBO accounts
    create new Odoo accounts or are deferred to manual mapping.
    """

    def _make_qb_account(self, qb_id, name, acct_type='Expense', code=None):
        data = {
            'Id': qb_id,
            'SyncToken': '0',
            'Name': name,
            'AccountType': acct_type,
            'Active': True,
            'MetaData': {'LastUpdatedTime': '2026-01-15T10:00:00Z'},
        }
        if code is not None:
            data['AcctNum'] = code
        return data

    def _Account(self):
        return self.env['account.account']

    def _account_in_company(self, code):
        domain = [('code', '=', code)]
        Account = self._Account()
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', self.company.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', 'in', [self.company.id, False]))
        return Account.search(domain, limit=1)

    def test_map_only_links_existing_account_by_code_and_skips_create(self):
        existing = self._Account().with_context(skip_qb_sync=True).create({
            'name': 'Office Supplies',
            'code': '650001',
            'account_type': 'expense',
        })
        self.config.account_strategy = 'map_only'
        records = [self._make_qb_account('801', 'Office Supplies', 'Expense', '650001')]
        client = self._mock_client()
        client.query_all.return_value = records

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        existing.invalidate_recordset(['qb_account_id'])
        self.assertEqual(existing.qb_account_id, '801',
                         'map_only should link the existing Odoo account by code')
        # No second account should have been created.
        self.assertFalse(
            self._Account().search([('code', '=', '650001-QB')]),
            'map_only must not create suffixed duplicate accounts',
        )
        self.assertEqual(self.config.qb_account_mapped_count, 1)
        self.assertEqual(self.config.qb_account_unmapped_count, 0)

    def test_map_only_does_not_create_when_no_match(self):
        self.config.account_strategy = 'map_only'
        records = [self._make_qb_account(
            '900', 'Brand New QBO Account', 'Other Current Asset', '199999',
        )]
        client = self._mock_client()
        client.query_all.return_value = records

        existing_count_before = self._Account().search_count([])
        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        self.assertEqual(self._Account().search_count([]), existing_count_before,
                         'map_only must not create new accounts')
        warning_logs = self.env['quickbooks.sync.log'].search([
            ('entity_type', '=', 'account'),
            ('state', '=', 'warning'),
            ('qb_entity_id', '=', '900'),
        ])
        self.assertTrue(warning_logs, 'unmapped accounts must be logged as warning')
        self.assertEqual(self.config.qb_account_unmapped_count, 1)

    def test_create_missing_creates_new_account_when_no_match(self):
        self.config.account_strategy = 'create_missing'
        records = [self._make_qb_account(
            '901', 'Auto-Created QBO Account', 'Expense', '199998',
        )]
        client = self._mock_client()
        client.query_all.return_value = records

        self.env['qb.sync.accounts'].pull_all(client, self.config, 'account')

        created = self._Account().search([('qb_account_id', '=', '901')], limit=1)
        self.assertTrue(created, 'create_missing must create when no match')
        self.assertEqual(created.name, 'Auto-Created QBO Account')
        self.assertEqual(created.account_type, 'expense')
