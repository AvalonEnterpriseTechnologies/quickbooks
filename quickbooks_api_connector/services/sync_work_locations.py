import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncWorkLocations(models.AbstractModel):
    _name = 'qb.sync.work.locations'
    _description = 'QuickBooks Employee Work Location Sync'

    def push(self, client, config, job):
        _logger.info('Skipping work location push; QBO exposes these as read-only.')
        return {}

    def pull(self, client, config, job):
        if not job.qb_entity_id:
            return {}
        data = client.read('EmployeeWorkLocation', job.qb_entity_id).get(
            'EmployeeWorkLocation', {}
        )
        if not data:
            return {}
        self._upsert_location(data, config)
        return {'qb_id': str(data.get('Id'))}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        for data in client.query_all('EmployeeWorkLocation'):
            self._upsert_location(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping work location push_all; QBO exposes these as read-only.')

    def _upsert_location(self, data, config):
        if 'hr.work.location' not in self.env:
            _logger.warning("hr module not installed — skipping work location sync")
            return False
        qb_id = str(data.get('Id') or '')
        if not qb_id:
            return False
        addr = data.get('Address') or data.get('PrimaryAddr') or {}
        partner = self._work_location_partner(addr, config)
        vals = {
            'qb_work_location_id': qb_id,
            'name': data.get('Name') or qb_id,
            'qb_last_synced': fields.Datetime.now(),
        }
        Location = self.env['hr.work.location']
        if 'active' in Location._fields:
            vals['active'] = bool(data.get('Active', True))
        if partner and 'address_id' in Location._fields:
            vals['address_id'] = partner.id
        existing = Location.search([
            ('qb_work_location_id', '=', qb_id),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Location.create(vals)

    def _work_location_partner(self, addr, config):
        if not addr:
            return False
        Partner = self.env['res.partner'].sudo()
        vals = {
            'name': addr.get('Line1') or 'QuickBooks Work Location',
            'street': addr.get('Line1') or False,
            'city': addr.get('City') or False,
            'zip': addr.get('PostalCode') or False,
            'company_id': config.company_id.id,
        }
        country_code = addr.get('Country')
        if country_code:
            country = self.env['res.country'].search([
                '|', ('code', '=', country_code), ('name', '=', country_code),
            ], limit=1)
            vals['country_id'] = country.id or False
        state_code = addr.get('CountrySubDivisionCode')
        if state_code and vals.get('country_id'):
            state = self.env['res.country.state'].search([
                ('code', '=', state_code),
                ('country_id', '=', vals['country_id']),
            ], limit=1)
            vals['state_id'] = state.id or False
        return Partner.create(vals)
