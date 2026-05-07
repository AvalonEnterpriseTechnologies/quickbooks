from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncJournalEntries(QuickbooksTestCommon):

    def test_qb_je_to_odoo_mapping(self):
        """Test QBO JournalEntry → Odoo account.move mapping."""
        service = self.env['qb.sync.journal.entries']
        qb_data = self._make_qb_journal_entry()['JournalEntry']
        vals = service._qb_je_to_odoo(qb_data, self.config)

        self.assertEqual(vals['move_type'], 'entry')
        self.assertEqual(vals['qb_je_id'], '700')
        self.assertTrue(vals.get('line_ids'))
        self.assertEqual(len(vals['line_ids']), 2)

        debit_line = vals['line_ids'][0][2]
        self.assertEqual(debit_line['debit'], 1000.00)
        self.assertEqual(debit_line['credit'], 0.0)

        credit_line = vals['line_ids'][1][2]
        self.assertEqual(credit_line['debit'], 0.0)
        self.assertEqual(credit_line['credit'], 1000.00)

    def test_push_journal_entry(self):
        """Test pushing a journal entry to QBO."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        if not journal:
            self.skipTest('No general journal available')

        accounts = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
        ], limit=2)
        if len(accounts) < 2:
            self.skipTest('Need at least 2 accounts')

        move = self.env['account.move'].with_context(skip_qb_sync=True).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {
                    'name': 'Debit',
                    'account_id': accounts[0].id,
                    'debit': 500.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Credit',
                    'account_id': accounts[1].id,
                    'debit': 0.0,
                    'credit': 500.0,
                }),
            ],
        })

        client = self._mock_client()
        client.create.return_value = {
            'JournalEntry': {'Id': '750', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'journal_entry'
        job.odoo_record_id = move.id
        job.odoo_model = 'account.move'

        service = self.env['qb.sync.journal.entries']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '750')

    def test_pull_creates_journal_entry(self):
        client = self._mock_client()
        client.read.return_value = self._make_qb_journal_entry(qb_id='751')

        job = MagicMock()
        job.entity_type = 'journal_entry'
        job.qb_entity_id = '751'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.journal.entries']
        result = service.pull(client, self.config, job)

        move = self.env['account.move'].search([
            ('qb_je_id', '=', '751'),
        ], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.move_type, 'entry')
