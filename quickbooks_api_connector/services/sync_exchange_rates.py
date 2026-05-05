import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncExchangeRates(models.AbstractModel):
    _name = 'qb.sync.exchange.rates'
    _description = 'QuickBooks Exchange Rate Sync (pull only)'

    def pull(self, client, config, job):
        return {}

    def push(self, client, config, job):
        _logger.info('QBO ExchangeRate is treated as pull-only by this connector.')
        return {}

    def pull_all(self, client, config, entity_type):
        """Pull exchange rates from QBO and update Odoo res.currency.rate.

        QBO stores exchange rates per currency pair. The API endpoint is:
        GET /v3/company/{realmId}/exchangerate?sourcecurrencycode=EUR
        """
        home_currency = config.company_id.currency_id
        if not home_currency:
            return

        foreign_currencies = self.env['res.currency'].search([
            ('active', '=', True),
            ('id', '!=', home_currency.id),
        ])

        for currency in foreign_currencies:
            try:
                resp = client.get(
                    'exchangerate?sourcecurrencycode=%s' % currency.name
                )
                rate_data = resp.get('ExchangeRate', {})
                if not rate_data:
                    continue

                qb_rate = rate_data.get('Rate')
                as_of = rate_data.get('AsOfDate')
                if not qb_rate:
                    continue

                CurrencyRate = self.env['res.currency.rate']
                existing = CurrencyRate.search([
                    ('currency_id', '=', currency.id),
                    ('company_id', '=', config.company_id.id),
                    ('name', '=', as_of),
                ], limit=1)

                rate_val = 1.0 / float(qb_rate) if float(qb_rate) else 1.0

                if existing:
                    if existing.inverse_company_rate != float(qb_rate):
                        existing.write({'rate': rate_val})
                else:
                    CurrencyRate.create({
                        'currency_id': currency.id,
                        'company_id': config.company_id.id,
                        'name': as_of,
                        'rate': rate_val,
                    })

                _logger.info(
                    'Exchange rate synced: %s = %s (as of %s)',
                    currency.name, qb_rate, as_of,
                )
            except Exception:
                _logger.warning(
                    'Failed to pull exchange rate for %s', currency.name,
                    exc_info=True,
                )

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping ExchangeRate push_all; exchange rates are pulled from QBO.')
