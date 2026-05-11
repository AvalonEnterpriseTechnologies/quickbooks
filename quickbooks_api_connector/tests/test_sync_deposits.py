from unittest.mock import MagicMock

from odoo.addons.quickbooks_api_connector.services.qb_api_client import (
    QBApiError,
)
from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncDeposits(QuickbooksTestCommon):

    def _make_deposit_move(self, bank_qb_id='101', source_qb_id='401', amount=100.0):
        bank_account = self.env['account.account'].create({
            'name': 'QB Bank %s' % bank_qb_id,
            'code': '1010%s' % bank_qb_id,
            'account_type': 'asset_cash',
            'qb_account_id': bank_qb_id,
        })
        income_account = self.env['account.account'].create({
            'name': 'Deposit Source %s' % source_qb_id,
            'code': '4010%s' % source_qb_id,
            'account_type': 'income',
            'qb_account_id': source_qb_id,
        })
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': '2026-01-15',
            'line_ids': [
                (0, 0, {
                    'name': 'Bank',
                    'account_id': bank_account.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Source',
                    'account_id': income_account.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        return move, bank_account, income_account

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

    def test_push_skips_move_already_synced_as_journal_entry(self):
        move, _bank, _src = self._make_deposit_move()
        if 'qb_je_id' not in move._fields:
            self.skipTest('qb_je_id field not present on this build')
        move.with_context(skip_qb_sync=True).write({'qb_je_id': 'JE123'})

        client = self._mock_client()
        job = MagicMock()
        job.odoo_record_id = move.id

        result = self.env['qb.sync.deposits'].push(client, self.config, job)

        self.assertTrue(result.get('skipped'))
        client.create.assert_not_called()

    def test_payload_excludes_credit_lines_on_destination_account(self):
        # A transfer-style entry where the same bank account appears on both
        # debit and credit (different amounts) should not produce a deposit
        # source line for the bank itself.
        move, bank, source = self._make_deposit_move(amount=200.0)
        # Add an extra credit on the bank account to mimic an aggregated
        # transfer that nets to a deposit. The bank credit must NOT become
        # a DepositLineDetail line.
        self.env['account.move.line'].create({
            'move_id': move.id,
            'name': 'Bank counter-leg',
            'account_id': bank.id,
            'debit': 0.0,
            'credit': 50.0,
        })
        # Balance the books with an extra debit on the source account.
        self.env['account.move.line'].create({
            'move_id': move.id,
            'name': 'Adjustment',
            'account_id': source.id,
            'debit': 50.0,
            'credit': 0.0,
        })

        payload = self.env['qb.sync.deposits']._odoo_to_qb_deposit(move)

        self.assertEqual(payload['DepositToAccountRef']['value'], '101')
        self.assertEqual(len(payload['Line']), 1)
        self.assertEqual(
            payload['Line'][0]['DepositLineDetail']['AccountRef']['value'],
            '401',
        )

    def test_push_logs_payload_on_qbo_validation_error(self):
        move, _bank, _src = self._make_deposit_move()
        client = self._mock_client()
        client.create.side_effect = QBApiError(
            400, '{"Fault":{"Error":[{"code":"2020"}]}}', 'https://test',
        )
        job = MagicMock()
        job.odoo_record_id = move.id

        with self.assertLogs(
            'odoo.addons.quickbooks_api_connector.services.sync_deposits',
            level='ERROR',
        ) as captured:
            with self.assertRaises(QBApiError):
                self.env['qb.sync.deposits'].push(client, self.config, job)

        joined = '\n'.join(captured.output)
        self.assertIn('QBO Deposit push rejected', joined)
        self.assertIn('DepositToAccountRef', joined)

