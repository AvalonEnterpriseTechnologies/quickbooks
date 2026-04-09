import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncRefundReceipts(models.AbstractModel):
    _name = 'qb.sync.refund.receipts'
    _description = 'QuickBooks RefundReceipt Sync'

    def _odoo_to_qb_refundreceipt(self, move):
        lines = []
        for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
            detail = {
                'DetailType': 'SalesItemLineDetail',
                'Amount': abs(line.price_subtotal),
                'SalesItemLineDetail': {
                    'Qty': line.quantity,
                    'UnitPrice': line.price_unit,
                },
                'Description': line.name or '',
            }
            if line.product_id and line.product_id.qb_item_id:
                detail['SalesItemLineDetail']['ItemRef'] = {
                    'value': line.product_id.qb_item_id,
                }
            if line.tax_ids:
                tax = line.tax_ids[0]
                if hasattr(tax, 'qb_taxcode_id') and tax.qb_taxcode_id:
                    detail['SalesItemLineDetail']['TaxCodeRef'] = {
                        'value': tax.qb_taxcode_id,
                    }
            lines.append(detail)

        data = {
            'Line': lines,
            'TxnDate': move.invoice_date.isoformat() if move.invoice_date else None,
        }
        if move.partner_id and move.partner_id.qb_customer_id:
            data['CustomerRef'] = {'value': move.partner_id.qb_customer_id}
        if move.currency_id:
            data['CurrencyRef'] = {'value': move.currency_id.name}

        return {k: v for k, v in data.items() if v is not None}

    def _qb_refundreceipt_to_odoo(self, qb_data, config):
        vals = {
            'qb_refundreceipt_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }
        return vals

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        payload = self._odoo_to_qb_refundreceipt(move)
        qb_id = move.qb_refundreceipt_id

        if qb_id:
            existing = client.read('RefundReceipt', qb_id)
            entity = existing.get('RefundReceipt', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('RefundReceipt', payload)
        else:
            resp = client.create('RefundReceipt', payload)

        created = resp.get('RefundReceipt', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_refundreceipt_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('RefundReceipt', qb_id)
        qb_data = resp.get('RefundReceipt', {})
        if not qb_data:
            return {}

        vals = self._qb_refundreceipt_to_odoo(qb_data, config)
        existing = self.env['account.move'].search(
            [('qb_refundreceipt_id', '=', str(qb_data['Id']))], limit=1,
        )
        if existing:
            existing.with_context(skip_qb_sync=True).write(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('RefundReceipt', where_clause=where)
        Move = self.env['account.move']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_refundreceipt_to_odoo(qb_data, config)
            existing = Move.search([('qb_refundreceipt_id', '=', qb_id)], limit=1)
            if existing:
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        pass
