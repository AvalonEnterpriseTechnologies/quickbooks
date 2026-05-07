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
        qb_id = str(data.get('Id') or '')
        if not qb_id:
            return False
        addr = data.get('Address') or data.get('PrimaryAddr') or {}
        vals = {
            'company_id': config.company_id.id,
            'qb_work_location_id': qb_id,
            'name': data.get('Name') or qb_id,
            'active': bool(data.get('Active', True)),
            'line1': addr.get('Line1') or False,
            'city': addr.get('City') or False,
            'state_code': addr.get('CountrySubDivisionCode') or False,
            'postal_code': addr.get('PostalCode') or False,
            'country': addr.get('Country') or False,
            'qb_last_synced': fields.Datetime.now(),
        }
        Location = self.env['quickbooks.work.location']
        existing = Location.search([
            ('company_id', '=', config.company_id.id),
            ('qb_work_location_id', '=', qb_id),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Location.create(vals)
