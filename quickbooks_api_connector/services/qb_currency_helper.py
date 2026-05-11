from odoo import api, models


class QBCurrencyHelper(models.AbstractModel):
    _name = 'qb.currency.helper'
    _description = 'QuickBooks Currency Mapping Helper'

    @api.model
    def currency_vals(self, qb_data, config):
        vals = {}
        currency_ref = (qb_data or {}).get('CurrencyRef') or {}
        if currency_ref.get('value'):
            currency = self.env['res.currency'].search([
                ('name', '=', currency_ref['value']),
            ], limit=1)
            if currency:
                vals['currency_id'] = currency.id

        exchange_rate = self._float(qb_data.get('ExchangeRate'))
        if exchange_rate and 'qb_exchange_rate' in self.env['account.move']._fields:
            vals['qb_exchange_rate'] = exchange_rate

        home_total = self._float(
            qb_data.get('HomeTotalAmt')
            or qb_data.get('HomeBalance')
            or qb_data.get('HomeAmount')
        )
        if home_total is not None and 'qb_home_total_amt' in self.env['account.move']._fields:
            vals['qb_home_total_amt'] = home_total

        if vals.get('currency_id') and exchange_rate:
            self._ensure_rate(config, vals['currency_id'], qb_data, exchange_rate)
        return vals

    @api.model
    def payment_currency_vals(self, qb_data, config):
        vals = self.currency_vals(qb_data, config)
        move_only = {'qb_exchange_rate', 'qb_home_total_amt'}
        payment_vals = {}
        Payment = self.env['account.payment']
        for key, value in vals.items():
            payment_key = key
            if key == 'qb_home_total_amt':
                payment_key = 'qb_home_total_amt'
            if key in move_only and payment_key not in Payment._fields:
                continue
            if payment_key in Payment._fields:
                payment_vals[payment_key] = value
        return payment_vals

    def _ensure_rate(self, config, currency_id, qb_data, exchange_rate):
        currency = self.env['res.currency'].browse(currency_id)
        if currency == config.company_id.currency_id:
            return
        date_value = qb_data.get('TxnDate') or qb_data.get('AsOfDate')
        if not date_value:
            return
        rate = 1.0 / exchange_rate if exchange_rate else 1.0
        Rate = self.env['res.currency.rate'].sudo()
        existing = Rate.search([
            ('currency_id', '=', currency.id),
            ('company_id', '=', config.company_id.id),
            ('name', '=', date_value),
        ], limit=1)
        vals = {'rate': rate}
        if existing:
            existing.write(vals)
        else:
            vals.update({
                'currency_id': currency.id,
                'company_id': config.company_id.id,
                'name': date_value,
            })
            Rate.create(vals)

    @staticmethod
    def _float(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
