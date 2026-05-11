from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncDeposits(QuickbooksTestCommon):

    def test_pull_returns_id(self):
        client = self._mock_client()
        qb_data = self._make_qb_deposit()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1300'
        job.odoo_record_id = None
        job.entity_type = 'deposit'
        job.direction = 'pull'

        service = self.env['qb.sync.deposits']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1300')

    def test_push_skips_invalid_payload(self):
        bank_account = self.env['account.account'].create({
            'name': 'Unmapped Bank',
            'code': '102020',
            'account_type': 'asset_cash',
        })
        income_account = self.env['account.account'].create({
            'name': 'Unmapped Deposit Source',
            'code': '402020',
            'account_type': 'income',
        })
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': '2026-01-15',
            'line_ids': [
                (0, 0, {
                    'name': 'Bank',
                    'account_id': bank_account.id,
                    'debit': 100.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Source',
                    'account_id': income_account.id,
                    'debit': 0.0,
                    'credit': 100.0,
                }),
            ],
        })

        client = self._mock_client()
        job = MagicMock()
        job.odoo_record_id = move.id

        result = self.env['qb.sync.deposits'].push(client, self.config, job)

        self.assertTrue(result['skipped'])
        client.create.assert_not_called()
