"""QuickBooks SalesReceipt <-> Odoo account.move + account.payment sync.

A QBO SalesReceipt models a sale that was paid on the spot — the
customer hands over cash/check/card and the funds land directly in the
``DepositToAccountRef`` bank/undeposited-funds account. For the
historical migration we materialise that as:

* A posted Odoo ``out_invoice`` carrying the full QBO line grammar
  (item / discount / shipping / subtotal / note), so revenue reporting
  and AR aging look identical to QBO.
* A posted Odoo ``account.payment`` against the bank journal that maps
  to the QBO deposit account, auto-reconciled with the invoice's open
  receivable line so the AR balance ends at zero just like in QBO.

The bank-journal mapping reuses the resolver in ``qb.sync.payments`` so
operator intent (``account.journal.qb_account_id`` overrides) and the
``Apply QBO Account Mapping`` action are both honoured.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncSalesReceipts(models.AbstractModel):
    _name = 'qb.sync.sales.receipts'
    _description = 'QuickBooks Sales Receipt Sync'

    # ------------------------------------------------------------------
    # Odoo -> QBO (push, unchanged behaviour)
    # ------------------------------------------------------------------

    def _odoo_to_qb_salesreceipt(self, move):
        lines = []
        for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
            detail = {
                'DetailType': 'SalesItemLineDetail',
                'Amount': abs(line.price_total),
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

        return {k: v for k, v in data.items() if v is not None}

    # ------------------------------------------------------------------
    # QBO -> Odoo (pull)
    # ------------------------------------------------------------------

    def _qb_salesreceipt_to_odoo(self, qb_data, config):
        helpers = self.env['qb.sales.doc.helpers']
        Move = self.env['account.move']
        company = config.company_id

        vals = {
            'move_type': 'out_invoice',
            'qb_salesreceipt_id': str(qb_data.get('Id') or ''),
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
    # Auto-payment + reconcile
    # ------------------------------------------------------------------

    def _auto_reconcile_payment(self, move, qb_data, config):
        """Post move, create payment against the QBO deposit account, reconcile.

        Failures are non-fatal: the invoice remains in Odoo with a clear
        ``qb_sync_error`` so operators can finish reconciliation manually
        without blocking the rest of the historical sync.
        """
        if not move or not move.exists():
            return
        if move.move_type != 'out_invoice':
            return

        payments_service = self.env['qb.sync.payments']
        bank_journal = payments_service._resolve_bank_journal(
            qb_data, config, 'customer',
        )

        if move.state == 'draft':
            try:
                move.with_context(skip_qb_sync=True).action_post()
            except Exception as exc:
                _logger.warning(
                    'SalesReceipt-derived invoice %s could not be posted: %s',
                    move.id, exc,
                )
                if 'qb_sync_error' in move._fields:
                    move.with_context(skip_qb_sync=True).write({
                        'qb_sync_error': 'Auto-post failed: %s' % exc,
                    })
                return

        if not bank_journal:
            qbo_account_id = payments_service._extract_qbo_bank_ref(qb_data, 'customer')
            message = (
                'QBO SalesReceipt %s references deposit account id %s, but '
                'no Odoo bank journal is linked to it. Invoice posted but '
                'left unpaid; set account.journal.qb_account_id and re-run '
                'the relinker, or post the matching payment manually.'
            ) % (qb_data.get('Id') or '?', qbo_account_id or '?')
            _logger.warning(message)
            if 'qb_sync_error' in move._fields:
                move.with_context(skip_qb_sync=True).write({'qb_sync_error': message})
            return

        try:
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=move.ids,
                skip_qb_sync=True,
            ).create({
                'journal_id': bank_journal.id,
                'payment_date': move.invoice_date or fields.Date.context_today(self),
                'amount': move.amount_residual or move.amount_total,
            })
            wizard._create_payments()
        except Exception as exc:
            _logger.warning(
                'SalesReceipt-derived auto-payment failed for invoice %s: %s',
                move.id, exc,
            )
            if 'qb_sync_error' in move._fields:
                move.with_context(skip_qb_sync=True).write({
                    'qb_sync_error': 'Auto-payment failed: %s' % exc,
                })

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        payload = self._odoo_to_qb_salesreceipt(move)
        qb_id = move.qb_salesreceipt_id

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'sales_receipt', move)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(move, 'sales_receipt', entity)

        if qb_id:
            existing = client.read('SalesReceipt', qb_id)
            entity = existing.get('SalesReceipt', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('SalesReceipt', payload)
        else:
            resp = client.create('SalesReceipt', payload)

        created = resp.get('SalesReceipt', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_salesreceipt_id': str(created.get('Id', '')),
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
        resp = client.read('SalesReceipt', qb_id)
        qb_data = resp.get('SalesReceipt', {})
        if not qb_data:
            return {}
        return self._apply_pull(qb_data, config)

    def _apply_pull(self, qb_data, config):
        vals = self._qb_salesreceipt_to_odoo(qb_data, config)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('sales_receipt', qb_data, config.company_id)

        if existing:
            matcher.link_odoo_record(existing, 'sales_receipt', qb_data)
            line_vals = vals.pop('invoice_line_ids', [])
            existing.with_context(skip_qb_sync=True).write(vals)
            if line_vals and existing.state == 'draft':
                existing.invoice_line_ids.unlink()
                existing.with_context(skip_qb_sync=True).write({
                    'invoice_line_ids': line_vals,
                })
            self._auto_reconcile_payment(existing, qb_data, config)
            return {'qb_id': str(qb_data.get('Id', ''))}

        new_move = self.env['account.move'].with_context(
            skip_qb_sync=True,
        ).create(vals)
        self._auto_reconcile_payment(new_move, qb_data, config)
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
        for qb_data in client.query_all('SalesReceipt', where_clause=where):
            try:
                self._apply_pull(qb_data, config)
            except Exception:
                _logger.exception(
                    'Failed to import QBO SalesReceipt Id=%s',
                    qb_data.get('Id'),
                )

    def push_all(self, client, config, entity_type):
        moves = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('paid', 'in_payment')),
            ('qb_salesreceipt_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            queue.enqueue(
                entity_type='sales_receipt',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )
