"""QuickBooks RefundReceipt <-> Odoo account.move sync.

A RefundReceipt in QBO is a cash refund issued to the customer — most
commonly the back-half of a CreditMemo that was paid out. For the
historical migration we materialise it as an Odoo ``out_refund`` move
with full line items so AR balances reconcile, and rebuild the
``CreditMemo -> RefundReceipt`` link from QBO's ``LinkedTxn`` array via
``account.move.reversed_entry_id`` (or the relinker second pass when
the parent CreditMemo has not been imported yet).
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncRefundReceipts(models.AbstractModel):
    _name = 'qb.sync.refund.receipts'
    _description = 'QuickBooks RefundReceipt Sync'

    # ------------------------------------------------------------------
    # Odoo -> QBO (push)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # QBO -> Odoo (pull)
    # ------------------------------------------------------------------

    def _qb_refundreceipt_to_odoo(self, qb_data, config):
        helpers = self.env['qb.sales.doc.helpers']
        Move = self.env['account.move']
        company = config.company_id

        vals = {
            'move_type': 'out_refund',
            'qb_refundreceipt_id': str(qb_data.get('Id') or ''),
            'qb_sync_token': str(qb_data.get('SyncToken') or ''),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': company.id,
            'qb_raw_json': qb_data,
        }

        partner_id = helpers.resolve_partner_id(qb_data, company)
        if partner_id:
            vals['partner_id'] = partner_id

        if qb_data.get('TxnDate'):
            vals['invoice_date'] = qb_data['TxnDate']

        doc_number = (qb_data.get('DocNumber') or '').strip()
        if doc_number:
            vals['ref'] = doc_number
            if 'qb_doc_number' in Move._fields:
                vals['qb_doc_number'] = doc_number

        if qb_data.get('PrivateNote'):
            vals['narration'] = qb_data['PrivateNote']

        vals.update(self.env['qb.currency.helper'].currency_vals(qb_data, config))

        parsed = helpers.parse_qb_lines(qb_data, company)
        commands = []
        for line in parsed:
            line_vals = self._build_line(line, helpers)
            if line_vals:
                commands.append((0, 0, line_vals))
        if commands:
            vals['invoice_line_ids'] = commands

        credit_memos = helpers.collect_linked_txns(qb_data, 'CreditMemo')
        if credit_memos and 'qb_source_creditmemo_qb_id' in Move._fields:
            vals['qb_source_creditmemo_qb_id'] = credit_memos[0][0]

        return vals

    def _build_line(self, line, helpers):
        AccountMoveLine = self.env['account.move.line']
        qb_line_id = line.get('qb_line_id') or False

        def with_qb_id(vals):
            if qb_line_id and 'qb_line_id' in AccountMoveLine._fields:
                vals['qb_line_id'] = qb_line_id
            return vals

        kind = line['kind']
        if kind == 'item':
            return with_qb_id({
                'name': line.get('name') or '/',
                'product_id': line.get('product_id') or False,
                'quantity': line.get('qty') or 1.0,
                'price_unit': line.get('price_unit') or 0.0,
                'tax_ids': [(6, 0, line.get('tax_ids') or [])],
            })
        if kind == 'discount':
            product = helpers.get_or_create_qb_discount_product()
            return with_qb_id({
                'name': line.get('name') or 'Discount',
                'product_id': product.id,
                'quantity': 1.0,
                'price_unit': line.get('amount') or 0.0,
            })
        if kind == 'shipping':
            product = helpers.get_or_create_qb_shipping_product()
            return with_qb_id({
                'name': line.get('name') or 'Shipping',
                'product_id': product.id,
                'quantity': 1.0,
                'price_unit': line.get('amount') or 0.0,
            })
        if kind == 'section':
            return with_qb_id({
                'display_type': 'line_section',
                'name': line.get('name') or 'Subtotal',
            })
        if kind == 'note':
            return with_qb_id({
                'display_type': 'line_note',
                'name': line.get('name') or '',
            })
        return None

    # ------------------------------------------------------------------
    # Link to parent CreditMemo
    # ------------------------------------------------------------------

    def _post_link_to_parents(self, move, qb_data):
        helpers = self.env['qb.sales.doc.helpers']
        Move = self.env['account.move']
        if not move or not move.exists():
            return
        cms = helpers.collect_linked_txns(qb_data, 'CreditMemo')
        if not cms:
            return
        qb_cm_id = cms[0][0]
        source = Move.search([
            ('qb_creditmemo_id', '=', qb_cm_id),
            ('company_id', '=', move.company_id.id),
        ], limit=1)
        if source and 'reversed_entry_id' in Move._fields:
            move.with_context(skip_qb_sync=True).write({
                'reversed_entry_id': source.id,
            })

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        payload = self._odoo_to_qb_refundreceipt(move)
        qb_id = move.qb_refundreceipt_id

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'refund_receipt', move)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(move, 'refund_receipt', entity)

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

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('RefundReceipt', qb_id)
        qb_data = resp.get('RefundReceipt', {})
        if not qb_data:
            return {}
        return self._apply_pull(qb_data, config)

    def _apply_pull(self, qb_data, config):
        vals = self._qb_refundreceipt_to_odoo(qb_data, config)
        matcher = self.env['qb.record.matcher']
        post_helper = self.env['qb.sync.post.helper']
        existing = matcher.find_odoo_match('refund_receipt', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'refund_receipt', qb_data)
            line_vals = vals.pop('invoice_line_ids', [])
            existing.with_context(skip_qb_sync=True).write(vals)
            if line_vals and existing.state == 'draft':
                existing.invoice_line_ids.unlink()
                existing.with_context(skip_qb_sync=True).write({
                    'invoice_line_ids': line_vals,
                })
            self._post_link_to_parents(existing, qb_data)
            post_helper.post(existing, config)
            return {'qb_id': str(qb_data.get('Id', ''))}

        new_move = self.env['account.move'].with_context(
            skip_qb_sync=True,
        ).create(vals)
        self._post_link_to_parents(new_move, qb_data)
        post_helper.post(new_move, config)
        return {'qb_id': str(qb_data.get('Id', ''))}

    # ------------------------------------------------------------------
    # Bulk
    # ------------------------------------------------------------------

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        for qb_data in client.query_all('RefundReceipt', where_clause=where):
            try:
                self._apply_pull(qb_data, config)
            except Exception:
                _logger.exception(
                    'Failed to import QBO RefundReceipt Id=%s',
                    qb_data.get('Id'),
                )

    def push_all(self, client, config, entity_type):
        moves = self.env['account.move'].search([
            ('move_type', '=', 'out_refund'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('paid', 'in_payment')),
            ('qb_refundreceipt_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            queue.enqueue(
                entity_type='refund_receipt',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )
