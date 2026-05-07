from unittest.mock import MagicMock

from .common import QuickbooksTestCommon


class TestSyncPayments(QuickbooksTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Payment Customer',
            'customer_rank': 1,
            'qb_customer_id': '100',
        })

    def test_odoo_payment_to_qb_mapping(self):
        """Test Odoo customer payment → QBO Payment mapping."""
        payment = self.env['account.payment'].with_context(skip_qb_sync=True).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.customer.id,
            'amount': 199.98,
            'date': '2026-01-20',
        })
        service = self.env['qb.sync.payments']
        data = service._odoo_payment_to_qb(payment)

        self.assertEqual(data['TotalAmt'], 199.98)
        self.assertEqual(data['CustomerRef']['value'], '100')
        self.assertEqual(data['TxnDate'], '2026-01-20')

    def test_qb_payment_to_odoo_mapping(self):
        """Test QBO Payment → Odoo payment mapping."""
        service = self.env['qb.sync.payments']
        qb_data = self._make_qb_payment()['Payment']
        vals = service._qb_payment_to_odoo(qb_data, self.config)

        self.assertEqual(vals['payment_type'], 'inbound')
        self.assertEqual(vals['partner_type'], 'customer')
        self.assertEqual(vals['amount'], 199.98)
        self.assertEqual(vals['qb_payment_id'], '600')
        self.assertEqual(vals['partner_id'], self.customer.id)

    def test_push_creates_new_payment(self):
        payment = self.env['account.payment'].with_context(skip_qb_sync=True).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.customer.id,
            'amount': 100.00,
        })
        client = self._mock_client()
        client.create.return_value = {
            'Payment': {'Id': '650', 'SyncToken': '0'},
        }

        job = MagicMock()
        job.entity_type = 'payment'
        job.odoo_record_id = payment.id
        job.odoo_model = 'account.payment'

        service = self.env['qb.sync.payments']
        result = service.push(client, self.config, job)

        self.assertEqual(result['qb_id'], '650')

    def test_pull_creates_new_payment(self):
        client = self._mock_client()
        client.read.return_value = self._make_qb_payment(qb_id='651')

        job = MagicMock()
        job.entity_type = 'payment'
        job.qb_entity_id = '651'
        job.odoo_record_id = None
        job.write = MagicMock()

        service = self.env['qb.sync.payments']
        result = service.pull(client, self.config, job)

        payment = self.env['account.payment'].search([
            ('qb_payment_id', '=', '651'),
        ], limit=1)
        self.assertTrue(payment)
