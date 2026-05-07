import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QBSyncCustomers(models.AbstractModel):
    _name = 'qb.sync.customers'
    _description = 'QuickBooks Customer/Vendor Sync'

    # ---- Field Mapping ----

    def _odoo_to_qb_customer(self, partner):
        """Map an Odoo res.partner to a QBO Customer dict."""
        data = {
            'DisplayName': partner.name or '',
            'GivenName': (partner.name or '').split(' ')[0][:25],
            'FamilyName': ' '.join((partner.name or '').split(' ')[1:])[:25] or None,
            'CompanyName': partner.company_name or (
                partner.name if partner.company_type == 'company' else None
            ),
            'PrimaryEmailAddr': {'Address': partner.email} if partner.email else None,
            'PrimaryPhone': (
                {'FreeFormNumber': partner.phone} if partner.phone else None
            ),
            'Mobile': {'FreeFormNumber': partner.mobile} if partner.mobile else None,
            'BillAddr': self._odoo_address_to_qb(partner),
            'ShipAddr': self._odoo_address_to_qb(partner),
        }
        if partner.vat:
            data['ResaleNum'] = partner.vat
        if partner.website:
            data['WebAddr'] = {'URI': partner.website}

        data = {k: v for k, v in data.items() if v is not None}
        return data

    def _odoo_to_qb_vendor(self, partner):
        """Map an Odoo res.partner to a QBO Vendor dict."""
        data = {
            'DisplayName': partner.name or '',
            'GivenName': (partner.name or '').split(' ')[0][:25],
            'FamilyName': ' '.join((partner.name or '').split(' ')[1:])[:25] or None,
            'CompanyName': partner.company_name or (
                partner.name if partner.company_type == 'company' else None
            ),
            'PrimaryEmailAddr': {'Address': partner.email} if partner.email else None,
            'PrimaryPhone': (
                {'FreeFormNumber': partner.phone} if partner.phone else None
            ),
            'Mobile': {'FreeFormNumber': partner.mobile} if partner.mobile else None,
            'BillAddr': self._odoo_address_to_qb(partner),
        }
        if partner.vat:
            data['TaxIdentifier'] = partner.vat
        if partner.website:
            data['WebAddr'] = {'URI': partner.website}

        data = {k: v for k, v in data.items() if v is not None}
        return data

    def _qb_customer_to_odoo(self, qb_data):
        """Map a QBO Customer dict to Odoo res.partner vals."""
        vals = {
            'name': qb_data.get('DisplayName', ''),
            'email': (qb_data.get('PrimaryEmailAddr') or {}).get('Address', False),
            'phone': (qb_data.get('PrimaryPhone') or {}).get('FreeFormNumber', False),
            'mobile': (qb_data.get('Mobile') or {}).get('FreeFormNumber', False),
            'website': (qb_data.get('WebAddr') or {}).get('URI', False),
            'company_type': (
                'company' if qb_data.get('CompanyName') else 'person'
            ),
            'company_name': qb_data.get('CompanyName', False),
            'customer_rank': 1,
        }
        vat = qb_data.get('ResaleNum')
        if vat:
            vals['vat'] = vat

        addr = qb_data.get('BillAddr') or {}
        vals.update(self._qb_address_to_odoo(addr))

        vals['qb_customer_id'] = str(qb_data.get('Id', ''))
        vals['qb_sync_token'] = str(qb_data.get('SyncToken', ''))
        vals['qb_last_synced'] = fields.Datetime.now()
        vals['qb_sync_error'] = False
        return vals

    def _qb_vendor_to_odoo(self, qb_data):
        """Map a QBO Vendor dict to Odoo res.partner vals."""
        vals = {
            'name': qb_data.get('DisplayName', ''),
            'email': (qb_data.get('PrimaryEmailAddr') or {}).get('Address', False),
            'phone': (qb_data.get('PrimaryPhone') or {}).get('FreeFormNumber', False),
            'mobile': (qb_data.get('Mobile') or {}).get('FreeFormNumber', False),
            'website': (qb_data.get('WebAddr') or {}).get('URI', False),
            'company_type': (
                'company' if qb_data.get('CompanyName') else 'person'
            ),
            'company_name': qb_data.get('CompanyName', False),
            'supplier_rank': 1,
        }
        vat = qb_data.get('TaxIdentifier')
        if vat:
            vals['vat'] = vat

        addr = qb_data.get('BillAddr') or {}
        vals.update(self._qb_address_to_odoo(addr))

        vals['qb_vendor_id'] = str(qb_data.get('Id', ''))
        vals['qb_sync_token'] = str(qb_data.get('SyncToken', ''))
        vals['qb_last_synced'] = fields.Datetime.now()
        vals['qb_sync_error'] = False
        return vals

    # ---- Address helpers ----

    def _odoo_address_to_qb(self, partner):
        addr = {}
        if partner.street:
            addr['Line1'] = partner.street
        if partner.street2:
            addr['Line2'] = partner.street2
        if partner.city:
            addr['City'] = partner.city
        if partner.state_id:
            addr['CountrySubDivisionCode'] = partner.state_id.code
        if partner.zip:
            addr['PostalCode'] = partner.zip
        if partner.country_id:
            addr['Country'] = partner.country_id.code
        return addr or None

    def _qb_address_to_odoo(self, addr):
        vals = {}
        if addr.get('Line1'):
            vals['street'] = addr['Line1']
        if addr.get('Line2'):
            vals['street2'] = addr['Line2']
        if addr.get('City'):
            vals['city'] = addr['City']
        if addr.get('PostalCode'):
            vals['zip'] = addr['PostalCode']
        if addr.get('CountrySubDivisionCode'):
            state = self.env['res.country.state'].search([
                ('code', '=', addr['CountrySubDivisionCode']),
            ], limit=1)
            if state:
                vals['state_id'] = state.id
        if addr.get('Country'):
            country = self.env['res.country'].search([
                ('code', '=', addr['Country']),
            ], limit=1)
            if country:
                vals['country_id'] = country.id
        return vals

    # ---- Push (Odoo → QBO) ----

    def push(self, client, config, job):
        """Push a single partner to QBO."""
        partner = self.env['res.partner'].browse(job.odoo_record_id)
        if not partner.exists():
            _logger.warning('Partner %d no longer exists, skipping push', job.odoo_record_id)
            return {}

        is_customer = job.entity_type == 'customer'
        qb_id_field = 'qb_customer_id' if is_customer else 'qb_vendor_id'
        qb_entity_name = 'Customer' if is_customer else 'Vendor'
        mapper = self._odoo_to_qb_customer if is_customer else self._odoo_to_qb_vendor
        qb_id = getattr(partner, qb_id_field)

        payload = mapper(partner)

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity_data = matcher.find_qbo_match(client, job.entity_type, partner)
            if entity_data:
                qb_id = str(entity_data.get('Id', ''))
                matcher.link_odoo_record(partner, job.entity_type, entity_data)

        if qb_id:
            # Update existing
            if 'entity_data' not in locals() or not entity_data:
                existing = client.read(qb_entity_name, qb_id)
                entity_data = existing.get(qb_entity_name, {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update(qb_entity_name, payload)
        else:
            resp = client.create(qb_entity_name, payload)

        created_data = resp.get(qb_entity_name, {})
        new_id = str(created_data.get('Id', ''))
        new_token = str(created_data.get('SyncToken', ''))

        partner.with_context(skip_qb_sync=True).write({
            qb_id_field: new_id,
            'qb_sync_token': new_token,
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': new_id}

    # ---- Pull (QBO → Odoo) ----

    def pull(self, client, config, job):
        """Pull a single customer/vendor from QBO into Odoo."""
        is_customer = job.entity_type == 'customer'
        qb_entity_name = 'Customer' if is_customer else 'Vendor'
        qb_id_field = 'qb_customer_id' if is_customer else 'qb_vendor_id'
        mapper = self._qb_customer_to_odoo if is_customer else self._qb_vendor_to_odoo

        if job.qb_entity_id:
            resp = client.read(qb_entity_name, job.qb_entity_id)
            qb_data = resp.get(qb_entity_name, {})
        elif job.odoo_record_id:
            partner = self.env['res.partner'].browse(job.odoo_record_id)
            qb_id = getattr(partner, qb_id_field)
            if not qb_id:
                return {}
            resp = client.read(qb_entity_name, qb_id)
            qb_data = resp.get(qb_entity_name, {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = mapper(qb_data)
        qb_id = str(qb_data.get('Id', ''))

        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match(job.entity_type, qb_data, config.company_id)

        if existing:
            matcher.link_odoo_record(existing, job.entity_type, qb_data)
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, job.entity_type)
            if decision == 'qbo':
                existing.with_context(skip_qb_sync=True).write(vals)
            elif decision == 'conflict':
                job.write({'state': 'conflict'})
                return {'qb_id': qb_id}
            # 'odoo' or 'skip' -> do nothing on Odoo side
        else:
            self.env['res.partner'].with_context(skip_qb_sync=True).create(vals)

        return {'qb_id': qb_id}

    # ---- Bulk operations ----

    def pull_all(self, client, config, entity_type):
        """Pull all customers or vendors from QBO."""
        is_customer = entity_type == 'customer'
        qb_entity_name = 'Customer' if is_customer else 'Vendor'
        qb_id_field = 'qb_customer_id' if is_customer else 'qb_vendor_id'
        mapper = self._qb_customer_to_odoo if is_customer else self._qb_vendor_to_odoo

        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )

        records = client.query_all(qb_entity_name, where_clause=where)
        Partner = self.env['res.partner']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = mapper(qb_data)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match(entity_type, qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, entity_type, qb_data)
                resolver = self.env['qb.conflict.resolver']
                decision = resolver.resolve(config, existing, qb_data, entity_type)
                if decision == 'qbo':
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Partner.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        """Push all unsynced partners to QBO."""
        is_customer = entity_type == 'customer'
        qb_id_field = 'qb_customer_id' if is_customer else 'qb_vendor_id'
        rank_field = 'customer_rank' if is_customer else 'supplier_rank'

        partners = self.env['res.partner'].search([
            (rank_field, '>', 0),
            (qb_id_field, '=', False),
            ('qb_do_not_sync', '=', False),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for partner in partners:
            queue.enqueue(
                entity_type=entity_type,
                direction='push',
                operation='create',
                odoo_record_id=partner.id,
                odoo_model='res.partner',
                company=config.company_id,
            )
