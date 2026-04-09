import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncCompanyInfo(models.AbstractModel):
    _name = 'qb.sync.company.info'
    _description = 'QuickBooks CompanyInfo Sync (pull only)'

    def pull(self, client, config, job):
        return self._pull_company_info(client, config)

    def push(self, client, config, job):
        return {}

    def _pull_company_info(self, client, config):
        """Pull company metadata from QBO and update the QB config and res.company."""
        try:
            resp = client.get('companyinfo/%s' % config.realm_id)
        except Exception:
            _logger.exception('Failed to pull CompanyInfo')
            return {}

        info = resp.get('CompanyInfo', {})
        if not info:
            return {}

        config.write({
            'qb_company_name': info.get('CompanyName', ''),
        })

        company = config.company_id
        company_vals = {}

        legal_name = info.get('LegalName')
        if legal_name and not company.name:
            company_vals['name'] = legal_name

        addr = info.get('CompanyAddr', {})
        if addr:
            if addr.get('Line1') and not company.street:
                company_vals['street'] = addr['Line1']
            if addr.get('City') and not company.city:
                company_vals['city'] = addr['City']
            if addr.get('PostalCode') and not company.zip:
                company_vals['zip'] = addr['PostalCode']
            if addr.get('CountrySubDivisionCode'):
                state = self.env['res.country.state'].search([
                    ('code', '=', addr['CountrySubDivisionCode']),
                ], limit=1)
                if state and not company.state_id:
                    company_vals['state_id'] = state.id
            if addr.get('Country'):
                country = self.env['res.country'].search([
                    ('code', '=', addr['Country']),
                ], limit=1)
                if country and not company.country_id:
                    company_vals['country_id'] = country.id

        email = (info.get('Email') or {}).get('Address')
        if email and not company.email:
            company_vals['email'] = email

        phone = (info.get('PrimaryPhone') or {}).get('FreeFormNumber')
        if phone and not company.phone:
            company_vals['phone'] = phone

        website_uri = (info.get('WebAddr') or {}).get('URI')
        if website_uri and not company.website:
            company_vals['website'] = website_uri

        fiscal_year_start = info.get('FiscalYearStartMonth')
        if fiscal_year_start:
            company_vals['fiscalyear_last_month'] = str(
                (int(fiscal_year_start) - 2) % 12 + 1
            )

        home_currency = (info.get('HomeCurrency') or {}).get('value')
        if home_currency:
            currency = self.env['res.currency'].search([
                ('name', '=', home_currency),
            ], limit=1)
            if currency and currency != company.currency_id:
                _logger.info(
                    'QBO home currency is %s, Odoo company currency is %s. '
                    'Skipping automatic currency change.',
                    home_currency, company.currency_id.name,
                )

        if company_vals:
            company.sudo().write(company_vals)
            _logger.info(
                'Updated company %s from QBO CompanyInfo: %s',
                company.name, list(company_vals.keys()),
            )

        return {'qb_id': str(info.get('Id', config.realm_id))}

    def pull_all(self, client, config, entity_type):
        self._pull_company_info(client, config)

    def push_all(self, client, config, entity_type):
        pass
