from unittest.mock import MagicMock

from odoo.tests.common import tagged

from .common import QuickbooksTestCommon


@tagged('post_install', '-at_install')
class TestSyncTerms(QuickbooksTestCommon):

    def test_pull_creates_payment_term(self):
        client = self._mock_client()
        qb_data = self._make_qb_term()
        client.read.return_value = qb_data

        job = MagicMock()
        job.qb_entity_id = '1500'
        job.odoo_record_id = None
        job.entity_type = 'term'
        job.direction = 'pull'

        service = self.env['qb.sync.terms']
        result = service.pull(client, self.config, job)
        self.assertEqual(result.get('qb_id'), '1500')

        term = self.env['account.payment.term'].search(
            [('qb_term_id', '=', '1500')]
        )
        self.assertTrue(term)
        self.assertEqual(term.name, 'Net 30')
