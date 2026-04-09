import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncVendorCredits(models.AbstractModel):
    _name = 'qb.sync.vendor.credits'
    _description = 'QuickBooks VendorCredit Sync'

    def _odoo_to_qb_vendorcredit(self, move):
        vendor_ref = None
        if move.partner_id and move.partner_id.qb_vendor_id:
            vendor_ref = {
                'value': move.partner_id.qb_vendor_id,
                'name': move.partner_id.name,
            }

        lines = []
        for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
            qb_line = {
                'DetailType': 'AccountBasedExpenseLineDetail',
                'Amount': abs(line.price_subtotal),
                'Description': (line.name or '')[:4000],
                'AccountBasedExpenseLineDetail': {},
            }
            if line.product_id and line.product_id.qb_item_id:
                qb_line['DetailType'] = 'ItemBasedExpenseLineDetail'
                qb_line['ItemBasedExpenseLineDetail'] = {
                    'ItemRef': {
                        'value': line.product_id.qb_item_id,
                        'name': line.product_id.name,
                    },
                    'Qty': line.quantity,
                    'UnitPrice': line.price_unit,
                }
                del qb_line['AccountBasedExpenseLineDetail']
            else:
                account = line.account_id
                if account and account.qb_account_id:
                    qb_line['AccountBasedExpenseLineDetail']['AccountRef'] = {
                        'value': account.qb_account_id,
                    }

            if line.tax_ids:
                tax = line.tax_ids[0]
                if tax.qb_taxcode_id:
                    detail_key = (
                        'ItemBasedExpenseLineDetail'
                        if qb_line['DetailType'] == 'ItemBasedExpenseLineDetail'
                        else 'AccountBasedExpenseLineDetail'
                    )
                    qb_line[detail_key]['TaxCodeRef'] = {
                        'value': tax.qb_taxcode_id,
                    }
            lines.append(qb_line)

        data = {
            'Line': lines,
            'TxnDate': move.invoice_date.isoformat() if move.invoice_date else None,
            'DocNumber': move.ref or move.name or '',
            'PrivateNote': (move.narration or '')[:4000] or None,
        }
        if vendor_ref:
            data['VendorRef'] = vendor_ref
        if move.currency_id:
            data['CurrencyRef'] = {'value': move.currency_id.name}

        return {k: v for k, v in data.items() if v is not None}

    def _qb_vendorcredit_to_odoo(self, qb_data, config):
        vals = {
            'move_type': 'in_refund',
            'qb_vendorcredit_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': config.company_id.id,
        }

        vendor_ref = qb_data.get('VendorRef', {})
        if vendor_ref.get('value'):
            partner = self.env['res.partner'].search([
                ('qb_vendor_id', '=', vendor_ref['value']),
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id

        if qb_data.get('TxnDate'):
            vals['invoice_date'] = qb_data['TxnDate']
        if qb_data.get('DocNumber'):
            vals['ref'] = qb_data['DocNumber']
        if qb_data.get('PrivateNote'):
            vals['narration'] = qb_data['PrivateNote']

        currency_ref = qb_data.get('CurrencyRef', {})
        if currency_ref.get('value'):
            currency = self.env['res.currency'].search([
                ('name', '=', currency_ref['value']),
            ], limit=1)
            if currency:
                vals['currency_id'] = currency.id

        invoice_lines = []
        for qb_line in qb_data.get('Line', []):
            detail_type = qb_line.get('DetailType', '')
            line_vals = {
                'name': qb_line.get('Description', ''),
                'price_unit': 0.0,
                'quantity': 1,
            }

            if detail_type == 'ItemBasedExpenseLineDetail':
                detail = qb_line.get('ItemBasedExpenseLineDetail', {})
                line_vals['quantity'] = detail.get('Qty', 1)
                line_vals['price_unit'] = detail.get('UnitPrice', 0.0)
                item_ref = detail.get('ItemRef', {})
                if item_ref.get('value'):
                    product = self.env['product.product'].search([
                        ('qb_item_id', '=', item_ref['value']),
                    ], limit=1)
                    if product:
                        line_vals['product_id'] = product.id
                self._apply_tax_ref(detail, line_vals, config)

            elif detail_type == 'AccountBasedExpenseLineDetail':
                detail = qb_line.get('AccountBasedExpenseLineDetail', {})
                line_vals['price_unit'] = qb_line.get('Amount', 0.0)
                account_ref = detail.get('AccountRef', {})
                if account_ref.get('value'):
                    account = self.env['account.account'].search([
                        ('qb_account_id', '=', account_ref['value']),
                        ('company_id', '=', config.company_id.id),
                    ], limit=1)
                    if account:
                        line_vals['account_id'] = account.id
                self._apply_tax_ref(detail, line_vals, config)
            else:
                continue

            invoice_lines.append((0, 0, line_vals))

        if invoice_lines:
            vals['invoice_line_ids'] = invoice_lines

        return vals

    def _apply_tax_ref(self, detail, line_vals, config):
        tax_ref = detail.get('TaxCodeRef', {})
        if tax_ref.get('value'):
            tax = self.env['account.tax'].search([
                ('qb_taxcode_id', '=', tax_ref['value']),
                ('company_id', '=', config.company_id.id),
            ], limit=1)
            if tax:
                line_vals['tax_ids'] = [(6, 0, [tax.id])]

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists() or move.move_type != 'in_refund':
            return {}

        payload = self._odoo_to_qb_vendorcredit(move)
        qb_id = move.qb_vendorcredit_id

        if qb_id:
            existing = client.read('VendorCredit', qb_id)
            entity_data = existing.get('VendorCredit', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('VendorCredit', payload)
        else:
            resp = client.create('VendorCredit', payload)

        created = resp.get('VendorCredit', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_vendorcredit_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        if job.qb_entity_id:
            resp = client.read('VendorCredit', job.qb_entity_id)
            qb_data = resp.get('VendorCredit', {})
        elif job.odoo_record_id:
            move = self.env['account.move'].browse(job.odoo_record_id)
            if not move.qb_vendorcredit_id:
                return {}
            resp = client.read('VendorCredit', move.qb_vendorcredit_id)
            qb_data = resp.get('VendorCredit', {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = self._qb_vendorcredit_to_odoo(qb_data, config)
        qb_id = str(qb_data.get('Id', ''))

        existing = self.env['account.move'].search([
            ('qb_vendorcredit_id', '=', qb_id),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, 'vendor_credit')
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
            self.env['account.move'].with_context(skip_qb_sync=True).create(vals)

        return {'qb_id': qb_id}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('VendorCredit', where_clause=where)
        Move = self.env['account.move']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_vendorcredit_to_odoo(qb_data, config)

            existing = Move.search([
                ('qb_vendorcredit_id', '=', qb_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)

            if existing:
                resolver = self.env['qb.conflict.resolver']
                if resolver.resolve(config, existing, qb_data, 'vendor_credit') == 'qbo':
                    vals.pop('invoice_line_ids', None)
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Move.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        moves = self.env['account.move'].search([
            ('move_type', '=', 'in_refund'),
            ('qb_vendorcredit_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('state', '=', 'posted'),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            queue.enqueue(
                entity_type='vendor_credit',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )
