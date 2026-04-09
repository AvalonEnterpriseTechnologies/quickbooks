import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTaxCodes(models.AbstractModel):
    _name = 'qb.sync.tax.codes'
    _description = 'QuickBooks Tax Code Sync'

    def _qb_taxcode_to_odoo(self, qb_data, tax_rates):
        """Map a QBO TaxCode to Odoo account.tax vals."""
        vals = {
            'name': qb_data.get('Name', 'Unknown Tax'),
            'qb_taxcode_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'type_tax_use': 'sale',
        }

        rate_detail = (
            qb_data.get('SalesTaxRateList', {}).get('TaxRateDetail', [])
        )
        if rate_detail:
            rate_ref = rate_detail[0].get('TaxRateRef', {}).get('value')
            if rate_ref and rate_ref in tax_rates:
                vals['amount'] = tax_rates[rate_ref].get('RateValue', 0.0)
                vals['qb_taxrate_id'] = rate_ref

        return vals

    def pull(self, client, config, job):
        if not job.qb_entity_id:
            return {}

        resp = client.read('TaxCode', job.qb_entity_id)
        qb_data = resp.get('TaxCode', {})
        if not qb_data:
            return {}

        tax_rates = self._fetch_tax_rates(client)
        vals = self._qb_taxcode_to_odoo(qb_data, tax_rates)
        qb_id = vals['qb_taxcode_id']

        existing = self.env['account.tax'].search([
            ('qb_taxcode_id', '=', qb_id),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            existing.write({
                'qb_sync_token': vals['qb_sync_token'],
                'qb_last_synced': vals['qb_last_synced'],
            })
        else:
            vals['company_id'] = config.company_id.id
            self.env['account.tax'].create(vals)

        return {'qb_id': qb_id}

    def push(self, client, config, job):
        # Tax codes are QB -> Odoo only
        return {}

    def pull_all(self, client, config, entity_type):
        """Pull all tax codes and rates from QBO."""
        tax_rates = self._fetch_tax_rates(client)
        records = client.query_all('TaxCode')
        Tax = self.env['account.tax']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_taxcode_to_odoo(qb_data, tax_rates)

            existing = Tax.search([
                ('qb_taxcode_id', '=', qb_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)

            if existing:
                existing.write({
                    'qb_sync_token': vals['qb_sync_token'],
                    'qb_last_synced': vals['qb_last_synced'],
                })
            else:
                vals['company_id'] = config.company_id.id
                Tax.create(vals)

    def push_all(self, client, config, entity_type):
        pass  # Tax codes are QB -> Odoo only

    def _fetch_tax_rates(self, client):
        """Fetch all TaxRate entities and return as dict keyed by Id."""
        rates = client.query_all('TaxRate')
        return {str(r.get('Id', '')): r for r in rates}
