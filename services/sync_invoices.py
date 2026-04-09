import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncInvoices(models.AbstractModel):
    _name = 'qb.sync.invoices'
    _description = 'QuickBooks Invoice / CreditMemo / Estimate Sync'

    # ---- Entity type routing ----

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

    # ---- Odoo → QBO mapping ----

    def _odoo_invoice_to_qb(self, move, meta):
        """Map an Odoo account.move (invoice/credit memo) to QBO format."""
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

        data = {k: v for k, v in data.items() if v is not None}
        return data

    # ---- QBO → Odoo mapping ----

    def _qb_invoice_to_odoo(self, qb_data, meta, config):
        """Map a QBO Invoice/CreditMemo to Odoo account.move vals."""
        vals = {
            'move_type': meta['move_type'],
            meta['qb_id_field']: str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }

        # Partner lookup
        customer_ref = qb_data.get('CustomerRef', {})
        if customer_ref.get('value'):
            partner = self.env['res.partner'].search([
                ('qb_customer_id', '=', customer_ref['value']),
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id

        if qb_data.get('TxnDate'):
            vals['invoice_date'] = qb_data['TxnDate']
        if qb_data.get('DueDate'):
            vals['invoice_date_due'] = qb_data['DueDate']
        if qb_data.get('DocNumber'):
            vals['ref'] = qb_data['DocNumber']
        if qb_data.get('PrivateNote'):
            vals['narration'] = qb_data['PrivateNote']

        # Currency
        currency_ref = qb_data.get('CurrencyRef', {})
        if currency_ref.get('value'):
            currency = self.env['res.currency'].search([
                ('name', '=', currency_ref['value']),
            ], limit=1)
            if currency:
                vals['currency_id'] = currency.id

        vals['company_id'] = config.company_id.id

        # Invoice lines
        invoice_lines = []
        for qb_line in qb_data.get('Line', []):
            detail_type = qb_line.get('DetailType', '')
            if detail_type == 'SalesItemLineDetail':
                detail = qb_line.get('SalesItemLineDetail', {})
                line_vals = {
                    'name': qb_line.get('Description', ''),
                    'quantity': detail.get('Qty', 1),
                    'price_unit': detail.get('UnitPrice', 0.0),
                }
                item_ref = detail.get('ItemRef', {})
                if item_ref.get('value'):
                    product = self.env['product.product'].search([
                        ('qb_item_id', '=', item_ref['value']),
                    ], limit=1)
                    if product:
                        line_vals['product_id'] = product.id

                tax_ref = detail.get('TaxCodeRef', {})
                if tax_ref.get('value'):
                    tax = self.env['account.tax'].search([
                        ('qb_taxcode_id', '=', tax_ref['value']),
                        ('company_id', '=', config.company_id.id),
                    ], limit=1)
                    if tax:
                        line_vals['tax_ids'] = [(6, 0, [tax.id])]

                invoice_lines.append((0, 0, line_vals))
            elif detail_type == 'SubTotalLineDetail':
                continue  # QBO auto-generates subtotal lines

        if invoice_lines:
            vals['invoice_line_ids'] = invoice_lines

        return vals

    # ---- Push ----

    def push(self, client, config, job):
        meta = self._get_meta(job.entity_type)
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        # Estimates use sale.order, skip if move_type doesn't match
        if meta['move_type'] and move.move_type != meta['move_type']:
            return {}

        payload = self._odoo_invoice_to_qb(move, meta)
        qb_id = getattr(move, meta['qb_id_field'])
        qb_name = meta['qb_name']

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

    # ---- Pull ----

    def pull(self, client, config, job):
        meta = self._get_meta(job.entity_type)
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

        vals = self._qb_invoice_to_odoo(qb_data, meta, config)
        qb_id = str(qb_data.get('Id', ''))

        existing = self.env['account.move'].search([
            (qb_id_field, '=', qb_id),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, job.entity_type)
            if decision == 'qbo':
                line_vals = vals.pop('invoice_line_ids', [])
                existing.with_context(skip_qb_sync=True).write(vals)
                if line_vals and existing.state == 'draft':
                    existing.invoice_line_ids.unlink()
                    existing.with_context(skip_qb_sync=True).write({
                        'invoice_line_ids': line_vals,
                    })
            elif decision == 'conflict':
                job.write({'state': 'conflict'})
        else:
            new_move = self.env['account.move'].with_context(
                skip_qb_sync=True,
            ).create(vals)

        return {'qb_id': qb_id}

    # ---- Bulk ----

    def pull_all(self, client, config, entity_type):
        meta = self._get_meta(entity_type)
        qb_name = meta['qb_name']
        qb_id_field = meta['qb_id_field']

        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all(qb_name, where_clause=where)
        Move = self.env['account.move']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_invoice_to_odoo(qb_data, meta, config)

            existing = Move.search([
                (qb_id_field, '=', qb_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)

            if existing:
                resolver = self.env['qb.conflict.resolver']
                if resolver.resolve(config, existing, qb_data, entity_type) == 'qbo':
                    line_vals = vals.pop('invoice_line_ids', [])
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Move.with_context(skip_qb_sync=True).create(vals)

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
