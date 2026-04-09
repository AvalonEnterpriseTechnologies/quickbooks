import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncTaxCodes(models.AbstractModel):
    _name = 'qb.sync.tax.codes'
    _description = 'QuickBooks Tax Code Sync'

    def _qb_taxcode_to_odoo_sale(self, qb_data, tax_rates):
        """Map QBO TaxCode to an Odoo sale-type account.tax."""
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

    def _qb_taxcode_to_odoo_purchase(self, qb_data, tax_rates):
        """Map QBO TaxCode to an Odoo purchase-type account.tax."""
        rate_detail = (
            qb_data.get('PurchaseTaxRateList', {}).get('TaxRateDetail', [])
        )
        if not rate_detail:
            return None

        vals = {
            'name': '%s (Purchase)' % qb_data.get('Name', 'Unknown Tax'),
            'qb_taxcode_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'type_tax_use': 'purchase',
        }

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
        qb_id = str(qb_data.get('Id', ''))

        self._upsert_sale_tax(qb_data, tax_rates, config)
        self._upsert_purchase_tax(qb_data, tax_rates, config)

        return {'qb_id': qb_id}

    def push(self, client, config, job):
        return {}

    def pull_all(self, client, config, entity_type):
        tax_rates = self._fetch_tax_rates(client)
        records = client.query_all('TaxCode')

        for qb_data in records:
            self._upsert_sale_tax(qb_data, tax_rates, config)
            self._upsert_purchase_tax(qb_data, tax_rates, config)

    def push_all(self, client, config, entity_type):
        pass

    def _upsert_sale_tax(self, qb_data, tax_rates, config):
        vals = self._qb_taxcode_to_odoo_sale(qb_data, tax_rates)
        qb_id = vals['qb_taxcode_id']
        Tax = self.env['account.tax']

        existing = Tax.search([
            ('qb_taxcode_id', '=', qb_id),
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            update_vals = {
                'name': vals['name'],
                'qb_sync_token': vals['qb_sync_token'],
                'qb_last_synced': vals['qb_last_synced'],
            }
            if 'amount' in vals:
                update_vals['amount'] = vals['amount']
            if 'qb_taxrate_id' in vals:
                update_vals['qb_taxrate_id'] = vals['qb_taxrate_id']
            existing.write(update_vals)
        else:
            vals['company_id'] = config.company_id.id
            Tax.create(vals)

    def _upsert_purchase_tax(self, qb_data, tax_rates, config):
        vals = self._qb_taxcode_to_odoo_purchase(qb_data, tax_rates)
        if not vals:
            return
        qb_id = vals['qb_taxcode_id']
        Tax = self.env['account.tax']

        existing = Tax.search([
            ('qb_taxcode_id', '=', qb_id),
            ('type_tax_use', '=', 'purchase'),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            update_vals = {
                'name': vals['name'],
                'qb_sync_token': vals['qb_sync_token'],
                'qb_last_synced': vals['qb_last_synced'],
            }
            if 'amount' in vals:
                update_vals['amount'] = vals['amount']
            if 'qb_taxrate_id' in vals:
                update_vals['qb_taxrate_id'] = vals['qb_taxrate_id']
            existing.write(update_vals)
        else:
            vals['company_id'] = config.company_id.id
            Tax.create(vals)

    def _fetch_tax_rates(self, client):
        rates = client.query_all('TaxRate')
        return {str(r.get('Id', '')): r for r in rates}
