"""QuickBooks Invoice / CreditMemo / Estimate sync.

Pull side is the load-bearing path for historical migration. Every QBO
Invoice and CreditMemo must produce an Odoo ``account.move`` with the
correct ``move_type``, partner, dates, document number, currency, full
line items (including discount / shipping / subtotal / note rows), and
the cross-document linkage encoded by QuickBooks' ``LinkedTxn`` array:

* ``Invoice.LinkedTxn[TxnType=Estimate]``    -> originating Odoo SO.
* ``CreditMemo.LinkedTxn[TxnType=Invoice]``  -> reversed Odoo invoice.

Per-line linkage is rebuilt by stamping every Odoo ``account.move.line``
with the originating QBO ``Line.Id``; the
``qb.sales.doc.relinker`` second-pass service then walks those ids to
populate ``account.move.line.sale_line_ids`` so Odoo's standard
"Invoiced / To invoice" reporting on the source SO works for imported
records too.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncInvoices(models.AbstractModel):
    _name = 'qb.sync.invoices'
    _description = 'QuickBooks Invoice / CreditMemo Sync'

    # ------------------------------------------------------------------
    # Entity type routing
    # ------------------------------------------------------------------

    _QB_ENTITY_MAP = {
        'invoice': {
            'qb_name': 'Invoice',
            'qb_id_field': 'qb_invoice_id',
            'move_type': 'out_invoice',
        },
        'credit_memo': {
            'qb_name': 'CreditMemo',
            'qb_id_field': 'qb_creditmemo_id',
            'move_type': 'out_refund',
        },
        'estimate': {
            'qb_name': 'Estimate',
            'qb_id_field': 'qb_invoice_id',
            'move_type': None,
        },
    }

    def _get_meta(self, entity_type):
        return self._QB_ENTITY_MAP.get(entity_type, self._QB_ENTITY_MAP['invoice'])

    # ------------------------------------------------------------------
    # Odoo -> QBO mapping (push, unchanged behaviour)
    # ------------------------------------------------------------------

    def _odoo_invoice_to_qb(self, move, meta):
        partner = move.partner_id
        customer_ref = None
        if partner and partner.qb_customer_id:
            customer_ref = {
                'value': partner.qb_customer_id,
                'name': partner.name,
            }

        lines = []
        for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
            qb_line = {
                'DetailType': 'SalesItemLineDetail',
                'Amount': abs(line.price_subtotal),
                'Description': (line.name or '')[:4000],
                'SalesItemLineDetail': {
                    'Qty': line.quantity,
                    'UnitPrice': line.price_unit,
                },
            }
            if line.product_id and line.product_id.qb_item_id:
                qb_line['SalesItemLineDetail']['ItemRef'] = {
                    'value': line.product_id.qb_item_id,
                    'name': line.product_id.name,
                }
            if line.tax_ids:
                tax = line.tax_ids[0]
                if tax.qb_taxcode_id:
                    qb_line['SalesItemLineDetail']['TaxCodeRef'] = {
                        'value': tax.qb_taxcode_id,
                    }
            if line.discount:
                qb_line['SalesItemLineDetail']['UnitPrice'] = (
                    line.price_unit * (1 - line.discount / 100.0)
                )
            lines.append(qb_line)

        data = {
            'Line': lines,
            'TxnDate': move.invoice_date.isoformat() if move.invoice_date else None,
            'DueDate': move.invoice_date_due.isoformat() if move.invoice_date_due else None,
            'DocNumber': move.name or '',
            'PrivateNote': (move.narration or '')[:4000] or None,
        }
        if customer_ref:
            data['CustomerRef'] = customer_ref

        if move.currency_id:
            data['CurrencyRef'] = {'value': move.currency_id.name}

        return {k: v for k, v in data.items() if v is not None}

    # ------------------------------------------------------------------
    # QBO -> Odoo mapping (pull)
    # ------------------------------------------------------------------

    def _qb_invoice_to_odoo(self, qb_data, meta, config):
        helpers = self.env['qb.sales.doc.helpers']
        Move = self.env['account.move']
        company = config.company_id

        vals = {
            'move_type': meta['move_type'],
            meta['qb_id_field']: str(qb_data.get('Id') or ''),
            'qb_sync_token': str(qb_data.get('SyncToken') or ''),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': company.id,
            'qb_raw_json': qb_data,
        }

        partner_id = helpers.resolve_partner_id(qb_data, company)
        if partner_id:
            vals['partner_id'] = partner_id
            partner = self.env['res.partner'].browse(partner_id)
            bill_addr = qb_data.get('BillAddr') or {}
            ship_addr = qb_data.get('ShipAddr') or {}
            if bill_addr:
                vals['partner_shipping_id'] = helpers.resolve_address_partner(
                    partner, ship_addr or bill_addr, 'delivery',
                )

        if qb_data.get('TxnDate'):
            vals['invoice_date'] = qb_data['TxnDate']
        if qb_data.get('DueDate'):
            vals['invoice_date_due'] = qb_data['DueDate']

        doc_number = (qb_data.get('DocNumber') or '').strip()
        if doc_number:
            vals['ref'] = doc_number
            if 'qb_doc_number' in Move._fields:
                vals['qb_doc_number'] = doc_number

        if qb_data.get('PrivateNote'):
            vals['narration'] = qb_data['PrivateNote']

        payment_term_id = helpers.resolve_payment_term_id(qb_data)
        if payment_term_id and 'invoice_payment_term_id' in Move._fields:
            vals['invoice_payment_term_id'] = payment_term_id

        vals.update(self.env['qb.currency.helper'].currency_vals(qb_data, config))

        line_commands = self._build_invoice_lines(qb_data, company)
        if line_commands:
            vals['invoice_line_ids'] = line_commands

        # Capture LinkedTxn references (resolved to Odoo records after
        # creation in _post_link_to_parents so we can fall back to a
        # second pass if the parent has not been imported yet).
        if meta['move_type'] == 'out_invoice':
            estimates = helpers.collect_linked_txns(qb_data, 'Estimate')
            if estimates:
                first_qb_id = estimates[0][0]
                if 'qb_source_estimate_qb_id' in Move._fields:
                    vals['qb_source_estimate_qb_id'] = first_qb_id
        if meta['move_type'] == 'out_refund' and meta['qb_id_field'] == 'qb_creditmemo_id':
            invoices = helpers.collect_linked_txns(qb_data, 'Invoice')
            if invoices and 'qb_source_invoice_qb_id' in Move._fields:
                vals['qb_source_invoice_qb_id'] = invoices[0][0]

        return vals

    def _build_invoice_lines(self, qb_data, company):
        helpers = self.env['qb.sales.doc.helpers']
        parsed = helpers.parse_qb_lines(qb_data, company)
        commands = []
        for line in parsed:
            line_vals = self._invoice_line_vals_for(line, helpers)
            if line_vals:
                commands.append((0, 0, line_vals))
        return commands

    def _invoice_line_vals_for(self, line, helpers):
        AccountMoveLine = self.env['account.move.line']
        qb_line_id = line.get('qb_line_id') or False
        kind = line['kind']

        def with_qb_id(vals):
            if qb_line_id and 'qb_line_id' in AccountMoveLine._fields:
                vals['qb_line_id'] = qb_line_id
            return vals

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
    # Post-create link resolution
    # ------------------------------------------------------------------

    def _post_link_to_parents(self, move, qb_data, meta):
        """Resolve LinkedTxn ids to Odoo records and stamp the move.

        Falls back gracefully when the parent QBO record has not been
        imported yet — the relinker second pass picks up where this
        leaves off. Per-line linkage to ``sale.order.line`` is populated
        via ``qb_line_id`` matching when the parent exists.
        """
        helpers = self.env['qb.sales.doc.helpers']
        Move = self.env['account.move']
        if not move or not move.exists():
            return

        if meta['move_type'] == 'out_invoice':
            estimates = helpers.collect_linked_txns(qb_data, 'Estimate')
            if estimates and 'qb_source_sale_order_id' in Move._fields and 'sale.order' in self.env:
                qb_estimate_id = estimates[0][0]
                sale_order = self.env['sale.order'].search([
                    ('qb_estimate_id', '=', qb_estimate_id),
                    ('company_id', '=', move.company_id.id),
                ], limit=1)
                if sale_order:
                    move.with_context(skip_qb_sync=True).write({
                        'qb_source_sale_order_id': sale_order.id,
                        'invoice_origin': move.invoice_origin or sale_order.name,
                    })
                    self._link_invoice_lines_to_sale_lines(move, sale_order)

        if meta['move_type'] == 'out_refund' and meta['qb_id_field'] == 'qb_creditmemo_id':
            invoices = helpers.collect_linked_txns(qb_data, 'Invoice')
            if invoices:
                qb_invoice_id = invoices[0][0]
                source = Move.search([
                    ('qb_invoice_id', '=', qb_invoice_id),
                    ('company_id', '=', move.company_id.id),
                ], limit=1)
                if source and 'reversed_entry_id' in Move._fields:
                    move.with_context(skip_qb_sync=True).write({
                        'reversed_entry_id': source.id,
                    })

    def _link_invoice_lines_to_sale_lines(self, move, sale_order):
        AccountMoveLine = self.env['account.move.line']
        if 'qb_line_id' not in AccountMoveLine._fields:
            return
        if 'sale.order.line' not in self.env:
            return
        if 'qb_line_id' not in self.env['sale.order.line']._fields:
            return
        so_lines_by_qb = {
            line.qb_line_id: line
            for line in sale_order.order_line
            if line.qb_line_id
        }
        if not so_lines_by_qb:
            return
        for inv_line in move.invoice_line_ids:
            if not inv_line.qb_line_id:
                continue
            so_line = so_lines_by_qb.get(inv_line.qb_line_id)
            if not so_line:
                continue
            if 'sale_line_ids' in inv_line._fields:
                inv_line.with_context(skip_qb_sync=True).write({
                    'sale_line_ids': [(6, 0, [so_line.id])],
                })

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_sales_payload(payload, move, qb_name):
        """QBO Invoice / CreditMemo requires CustomerRef + at least one Line.

        Returning a non-empty list aborts the API call so the queue never
        retries an obviously-broken payload. Same protection pattern as
        sync_transfers.push and sync_bills.push.
        """
        errors = []
        if not (payload.get('CustomerRef') or {}).get('value'):
            errors.append(
                'CustomerRef missing — set qb_customer_id on partner %s'
                % (move.partner_id.display_name if move.partner_id else '(none)')
            )
        lines = payload.get('Line') or []
        if not lines:
            errors.append('No exportable %s lines' % qb_name)
        return errors

    def push(self, client, config, job):
        meta = self._get_meta(job.entity_type)
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        if meta['move_type'] and move.move_type != meta['move_type']:
            return {}

        payload = self._odoo_invoice_to_qb(move, meta)
        errors = self._validate_sales_payload(payload, move, meta['qb_name'])
        if errors:
            error_msg = '%s push aborted before API call: %s' % (
                meta['qb_name'], '; '.join(errors),
            )
            _logger.warning(
                'Skipping QBO %s push for move %s: %s',
                meta['qb_name'], move.id, error_msg,
            )
            move.with_context(skip_qb_sync=True).write({'qb_sync_error': error_msg})
            return {'skipped': True, 'error': error_msg}

        qb_id = getattr(move, meta['qb_id_field'])
        qb_name = meta['qb_name']

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity_data = matcher.find_qbo_match(client, job.entity_type, move)
            if entity_data:
                qb_id = str(entity_data.get('Id', ''))
                matcher.link_odoo_record(move, job.entity_type, entity_data)

        if qb_id:
            existing = client.read(qb_name, qb_id)
            entity_data = existing.get(qb_name, {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update(qb_name, payload)
        else:
            resp = client.create(qb_name, payload)

        created = resp.get(qb_name, {})
        move.with_context(skip_qb_sync=True).write({
            meta['qb_id_field']: str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    def pull(self, client, config, job):
        entity_type = job.entity_type
        meta = self._get_meta(entity_type)
        qb_name = meta['qb_name']
        qb_id_field = meta['qb_id_field']

        if job.qb_entity_id:
            resp = client.read(qb_name, job.qb_entity_id)
            qb_data = resp.get(qb_name, {})
        elif job.odoo_record_id:
            move = self.env['account.move'].browse(job.odoo_record_id)
            qb_id = getattr(move, qb_id_field)
            if not qb_id:
                return {}
            resp = client.read(qb_name, qb_id)
            qb_data = resp.get(qb_name, {})
        else:
            return {}

        if not qb_data:
            return {}

        return self._apply_pull(qb_data, entity_type, meta, config, job=job)

    def _apply_pull(self, qb_data, entity_type, meta, config, job=None):
        vals = self._qb_invoice_to_odoo(qb_data, meta, config)
        qb_id = str(qb_data.get('Id') or '')

        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match(entity_type, qb_data, config.company_id)

        post_helper = self.env['qb.sync.post.helper']

        if existing:
            matcher.link_odoo_record(existing, entity_type, qb_data)
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, entity_type)
            if decision == 'qbo':
                line_vals = vals.pop('invoice_line_ids', [])
                existing.with_context(skip_qb_sync=True).write(vals)
                if line_vals and existing.state == 'draft':
                    existing.invoice_line_ids.unlink()
                    existing.with_context(skip_qb_sync=True).write({
                        'invoice_line_ids': line_vals,
                    })
                self._post_link_to_parents(existing, qb_data, meta)
                post_helper.post(existing, config)
            elif decision == 'conflict' and job is not None:
                job.write({'state': 'conflict'})
            else:
                # 'odoo' or 'skip' — keep linkage refresh because LinkedTxn
                # may now point at newly imported parents.
                self._post_link_to_parents(existing, qb_data, meta)
        else:
            new_move = self.env['account.move'].with_context(
                skip_qb_sync=True,
            ).create(vals)
            self._post_link_to_parents(new_move, qb_data, meta)
            post_helper.post(new_move, config)

        return {'qb_id': qb_id}

    # ------------------------------------------------------------------
    # Bulk
    # ------------------------------------------------------------------

    def pull_all(self, client, config, entity_type):
        meta = self._get_meta(entity_type)
        qb_name = meta['qb_name']

        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        for qb_data in client.query_all(qb_name, where_clause=where):
            try:
                self._apply_pull(qb_data, entity_type, meta, config)
            except Exception:
                _logger.exception(
                    'Failed to import QBO %s Id=%s',
                    qb_name, qb_data.get('Id'),
                )

    def push_all(self, client, config, entity_type):
        meta = self._get_meta(entity_type)
        if not meta['move_type']:
            return
        qb_id_field = meta['qb_id_field']

        moves = self.env['account.move'].search([
            ('move_type', '=', meta['move_type']),
            (qb_id_field, '=', False),
            ('qb_do_not_sync', '=', False),
            ('state', '=', 'posted'),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            queue.enqueue(
                entity_type=entity_type,
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )


