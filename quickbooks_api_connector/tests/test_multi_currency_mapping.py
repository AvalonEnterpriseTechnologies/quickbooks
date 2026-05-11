from .common import QuickbooksTestCommon


class TestMultiCurrencyMapping(QuickbooksTestCommon):

    def test_invoice_mapping_preserves_qbo_exchange_rate_and_home_total(self):
        eur = self.env['res.currency'].search([('name', '=', 'EUR')], limit=1)
        if not eur:
            self.skipTest('EUR currency is not available')
        qb_data = self._make_qb_invoice()['Invoice']
        qb_data.update({
            'CurrencyRef': {'value': 'EUR'},
            'ExchangeRate': 1.25,
            'HomeTotalAmt': 250.0,
        })

        vals = self.env['qb.sync.invoices']._qb_invoice_to_odoo(
            qb_data,
            {'move_type': 'out_invoice', 'qb_id_field': 'qb_invoice_id'},
            self.config,
        )

        self.assertEqual(vals['currency_id'], eur.id)
        self.assertEqual(vals['qb_exchange_rate'], 1.25)
        self.assertEqual(vals['qb_home_total_amt'], 250.0)

