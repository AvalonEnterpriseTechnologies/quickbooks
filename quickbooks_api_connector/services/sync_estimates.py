import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncEstimates(models.AbstractModel):
    _name = 'qb.sync.estimates'
    _description = 'QuickBooks Estimate Sync'

    def _check_model(self):
        if 'sale.order' not in self.env:
            _logger.warning('sale module not installed - skipping Estimate sync')
            return False
        return True

    def _odoo_estimate_to_qb(self, order):
        lines = []
        for line in order.order_line.filtered(lambda l: not l.display_type):
            detail = {
                'Qty': line.product_uom_qty,
                'UnitPrice': line.price_unit,
            }
            if line.product_id and line.product_id.qb_item_id:
                detail['ItemRef'] = {
                    'value': line.product_id.qb_item_id,
                    'name': line.product_id.name,
                }
            lines.append({
                'DetailType': 'SalesItemLineDetail',
                'Amount': line.price_subtotal,
                'Description': (line.name or '')[:4000],
                'SalesItemLineDetail': detail,
            })

        data = {
            'Line': lines,
            'TxnDate': order.date_order.date().isoformat() if order.date_order else None,
            'ExpirationDate': order.validity_date.isoformat() if order.validity_date else None,
            'DocNumber': order.name,
            'PrivateNote': (order.note or '')[:4000] or None,
        }
        if order.partner_id and order.partner_id.qb_customer_id:
            data['CustomerRef'] = {
                'value': order.partner_id.qb_customer_id,
                'name': order.partner_id.name,
            }
        if order.currency_id:
            data['CurrencyRef'] = {'value': order.currency_id.name}
        return {key: value for key, value in data.items() if value is not None}

    def _qb_estimate_to_odoo(self, qb_data, config):
        vals = {
            'company_id': config.company_id.id,
            'qb_estimate_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'note': qb_data.get('PrivateNote') or False,
        }
        customer_ref = qb_data.get('CustomerRef') or {}
        if customer_ref.get('value'):
            partner = self.env['res.partner'].search([
                ('qb_customer_id', '=', customer_ref['value']),
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id
        if qb_data.get('TxnDate'):
            vals['date_order'] = qb_data['TxnDate']
        if qb_data.get('ExpirationDate'):
            vals['validity_date'] = qb_data['ExpirationDate']
        lines = []
        for qb_line in qb_data.get('Line', []):
            if qb_line.get('DetailType') != 'SalesItemLineDetail':
                continue
            detail = qb_line.get('SalesItemLineDetail') or {}
            line_vals = {
                'name': qb_line.get('Description') or '',
                'product_uom_qty': detail.get('Qty', 1),
                'price_unit': detail.get('UnitPrice', 0.0),
            }
            item_ref = detail.get('ItemRef') or {}
            if item_ref.get('value'):
                product = self.env['product.product'].search([
                    ('qb_item_id', '=', item_ref['value']),
                ], limit=1)
                if product:
                    line_vals['product_id'] = product.id
            lines.append((0, 0, line_vals))
        if lines:
            vals['order_line'] = lines
        return vals

    def push(self, client, config, job):
        if not self._check_model():
            return {}
        order = self.env['sale.order'].browse(job.odoo_record_id)
        if not order.exists():
            return {}
        payload = self._odoo_estimate_to_qb(order)
        qb_id = order.qb_estimate_id
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'estimate', order)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(order, 'estimate', entity)
        if qb_id:
            existing = client.read('Estimate', qb_id)
            entity = existing.get('Estimate', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Estimate', payload)
        else:
            resp = client.create('Estimate', payload)
        created = resp.get('Estimate', {})
        order.with_context(skip_qb_sync=True).write({
            'qb_estimate_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        if not self._check_model() or not job.qb_entity_id:
            return {}
        resp = client.read('Estimate', job.qb_entity_id)
        qb_data = resp.get('Estimate', {})
        if not qb_data:
            return {}
        vals = self._qb_estimate_to_odoo(qb_data, config)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('estimate', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'estimate', qb_data)
            lines = vals.pop('order_line', [])
            existing.with_context(skip_qb_sync=True).write(vals)
            if lines and existing.state in ('draft', 'sent'):
                existing.order_line.unlink()
                existing.with_context(skip_qb_sync=True).write({'order_line': lines})
        else:
            self.env['sale.order'].with_context(skip_qb_sync=True).create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        for qb_data in client.query_all('Estimate', where_clause=where):
            job = self.env['quickbooks.sync.queue'].new({
                'qb_entity_id': str(qb_data.get('Id', '')),
            })
            self.pull(client, config, job)

    def push_all(self, client, config, entity_type):
        if not self._check_model():
            return
        orders = self.env['sale.order'].search([
            ('qb_estimate_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', '=', config.company_id.id),
            ('state', 'in', ('draft', 'sent', 'sale')),
        ])
        queue = self.env['quickbooks.sync.queue']
        for order in orders:
            queue.enqueue(
                entity_type='estimate',
                direction='push',
                operation='create',
                odoo_record_id=order.id,
                odoo_model='sale.order',
                company=config.company_id,
            )
