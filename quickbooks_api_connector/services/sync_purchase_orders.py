import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncPurchaseOrders(models.AbstractModel):
    _name = 'qb.sync.purchase.orders'
    _description = 'QuickBooks Purchase Order Sync'

    def _odoo_to_qb_po(self, order):
        lines = []
        for line in order.order_line:
            detail = {
                'DetailType': 'ItemBasedExpenseLineDetail',
                'Amount': line.price_total,
                'ItemBasedExpenseLineDetail': {
                    'Qty': line.product_qty,
                    'UnitPrice': line.price_unit,
                },
                'Description': line.name or '',
            }
            if line.product_id and line.product_id.qb_item_id:
                detail['ItemBasedExpenseLineDetail']['ItemRef'] = {
                    'value': line.product_id.qb_item_id,
                }
            lines.append(detail)

        data = {
            'Line': lines,
            'TxnDate': order.date_order.date().isoformat() if order.date_order else None,
        }
        if order.partner_id and order.partner_id.qb_vendor_id:
            data['VendorRef'] = {'value': order.partner_id.qb_vendor_id}

        return {k: v for k, v in data.items() if v is not None}

    def _qb_po_to_odoo(self, qb_data):
        vals = {
            'qb_po_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }
        return vals

    def push(self, client, config, job):
        order = self.env['purchase.order'].browse(job.odoo_record_id)
        if not order.exists():
            return {}

        payload = self._odoo_to_qb_po(order)
        qb_id = order.qb_po_id

        if qb_id:
            existing = client.read('PurchaseOrder', qb_id)
            entity = existing.get('PurchaseOrder', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('PurchaseOrder', payload)
        else:
            resp = client.create('PurchaseOrder', payload)

        created = resp.get('PurchaseOrder', {})
        order.with_context(skip_qb_sync=True).write({
            'qb_po_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('PurchaseOrder', qb_id)
        qb_data = resp.get('PurchaseOrder', {})
        if not qb_data:
            return {}

        vals = self._qb_po_to_odoo(qb_data)
        existing = self.env['purchase.order'].search(
            [('qb_po_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.write(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('PurchaseOrder', where_clause=where)
        PO = self.env['purchase.order']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_po_to_odoo(qb_data)
            existing = PO.search([('qb_po_id', '=', qb_id)], limit=1)
            if existing:
                existing.write(vals)

    def push_all(self, client, config, entity_type):
        orders = self.env['purchase.order'].search([
            ('qb_po_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('state', 'in', ['purchase', 'done']),
        ])
        queue = self.env['quickbooks.sync.queue']
        for order in orders:
            queue.enqueue(
                entity_type='purchase_order',
                direction='push',
                operation='create',
                odoo_record_id=order.id,
                odoo_model='purchase.order',
                company=config.company_id,
            )
