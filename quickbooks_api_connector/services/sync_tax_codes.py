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
        tax = self.env['account.tax'].browse(job.odoo_record_id)
        if not tax.exists():
            return {}
        if tax.qb_taxcode_id:
            _logger.info(
                'Skipping QBO TaxCode update for %s; existing tax codes are immutable',
                tax.name,
            )
            return {'qb_id': tax.qb_taxcode_id}

        payload = {
            'TaxCode': tax.name[:100],
            'TaxRateDetails': [{
                'TaxRateName': '%s Rate' % tax.name[:90],
                'RateValue': tax.amount,
                'TaxAgencyId': '1',
                'TaxApplicableOn': (
                    'Sales' if tax.type_tax_use == 'sale' else 'Purchase'
                ),
            }],
        }
        resp = client.post('taxservice/taxcode', payload)
        tax_code = resp.get('TaxCode', {})
        tax_rate = (resp.get('TaxRateDetails') or [{}])[0]
        tax.write({
            'qb_taxcode_id': str(tax_code.get('Id', '')),
            'qb_taxrate_id': str(tax_rate.get('TaxRateId', '')),
            'qb_sync_token': str(tax_code.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(tax_code.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        tax_rates = self._fetch_tax_rates(client)
        records = client.query_all('TaxCode')

        for qb_data in records:
            self._upsert_sale_tax(qb_data, tax_rates, config)
            self._upsert_purchase_tax(qb_data, tax_rates, config)

    def push_all(self, client, config, entity_type):
        taxes = self.env['account.tax'].search([
            ('company_id', '=', config.company_id.id),
            ('qb_taxcode_id', '=', False),
            ('type_tax_use', 'in', ('sale', 'purchase')),
        ])
        queue = self.env['quickbooks.sync.queue']
        for tax in taxes:
            queue.enqueue(
                entity_type='tax_code',
                direction='push',
                operation='create',
                odoo_record_id=tax.id,
                odoo_model='account.tax',
                company=config.company_id,
            )

    def _upsert_sale_tax(self, qb_data, tax_rates, config):
        vals = self._qb_taxcode_to_odoo_sale(qb_data, tax_rates)
        qb_id = vals['qb_taxcode_id']
        Tax = self.env['account.tax']

        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('tax_code', qb_data, config.company_id)
        if existing and existing.type_tax_use != 'sale':
            existing = Tax.browse()

        if existing:
            matcher.link_odoo_record(existing, 'tax_code', qb_data)
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

        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('tax_code', qb_data, config.company_id)
        if existing and existing.type_tax_use != 'purchase':
            existing = Tax.browse()

        if existing:
            matcher.link_odoo_record(existing, 'tax_code', qb_data)
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
