import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncEstimates(models.AbstractModel):
    """QuickBooks Estimate <-> Odoo sale.order sync.

    QBO has no SalesOrder entity, so its Estimates are imported as Odoo
    Quotations / Sales Orders. The pull side is the load-bearing path for
    historical migration: every QBO Estimate must produce an Odoo SO
    with matching DocNumber, customer, dates, payment terms, addresses,
    currency, and line items (including discount / shipping / subtotal /
    note rows). Each Odoo ``sale.order.line`` keeps the originating
    ``Line.Id`` in ``qb_line_id`` so ``qb.sales.doc.relinker`` can later
    rebuild Invoice-line -> Estimate-line links.
    """

    _name = 'qb.sync.estimates'
    _description = 'QuickBooks Estimate Sync'

    # ------------------------------------------------------------------
    # Capability checks
    # ------------------------------------------------------------------

    def _check_model(self):
        if 'sale.order' not in self.env:
            _logger.warning('sale module not installed - skipping Estimate sync')
            return False
        if 'qb_estimate_id' not in self.env['sale.order']._fields:
            _logger.warning(
                'sale.order is missing QuickBooks fields '
                '(quickbooks_api_connector_sale bridge did not load). '
                'Skipping Estimate sync.'
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Odoo -> QBO mapping (push)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # QBO -> Odoo mapping (pull)
    # ------------------------------------------------------------------

    def _qb_estimate_to_odoo(self, qb_data, config):
        helpers = self.env['qb.sales.doc.helpers']
        currency_helper = self.env['qb.currency.helper']
        SaleOrder = self.env['sale.order']
        company = config.company_id

        partner_id = helpers.resolve_partner_id(qb_data, company)
        partner = self.env['res.partner'].browse(partner_id) if partner_id else None

        vals = {
            'company_id': company.id,
            'qb_estimate_id': str(qb_data.get('Id') or ''),
            'qb_sync_token': str(qb_data.get('SyncToken') or ''),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'qb_raw_json': qb_data,
        }

        doc_number = (qb_data.get('DocNumber') or '').strip()
        if doc_number:
            vals['qb_doc_number'] = doc_number
            vals['client_order_ref'] = doc_number

        if partner_id:
            vals['partner_id'] = partner_id
            if partner:
                bill_addr = qb_data.get('BillAddr') or {}
                ship_addr = qb_data.get('ShipAddr') or {}
                vals['partner_invoice_id'] = helpers.resolve_address_partner(
                    partner, bill_addr, 'invoice',
                )
                vals['partner_shipping_id'] = helpers.resolve_address_partner(
                    partner, ship_addr, 'delivery',
                )

        if qb_data.get('TxnDate'):
            vals['date_order'] = qb_data['TxnDate']
        if qb_data.get('ExpirationDate'):
            vals['validity_date'] = qb_data['ExpirationDate']

        note = qb_data.get('PrivateNote') or qb_data.get('CustomerMemo', {}).get('value')
        if note:
            vals['note'] = note

        currency_vals = currency_helper.currency_vals(qb_data, config)
        if 'currency_id' in SaleOrder._fields and currency_vals.get('currency_id'):
            vals['pricelist_id'] = vals.get('pricelist_id') or False  # pricelist drives currency

        if 'pricelist_id' in vals and not vals['pricelist_id']:
            vals.pop('pricelist_id')

        payment_term_id = helpers.resolve_payment_term_id(qb_data)
        if payment_term_id and 'payment_term_id' in SaleOrder._fields:
            vals['payment_term_id'] = payment_term_id

        line_commands = self._build_order_lines(qb_data, company)
        if line_commands:
            vals['order_line'] = line_commands

        return vals

    def _build_order_lines(self, qb_data, company):
        helpers = self.env['qb.sales.doc.helpers']
        parsed = helpers.parse_qb_lines(qb_data, company)
        commands = []
        for line in parsed:
            line_vals = self._order_line_vals_for(line, helpers)
            if line_vals:
                commands.append((0, 0, line_vals))
        return commands

    def _order_line_vals_for(self, line, helpers):
        qb_line_id = line.get('qb_line_id') or False
        kind = line['kind']

        if kind == 'item':
            return {
                'name': line.get('name') or '/',
                'product_id': line.get('product_id') or False,
                'product_uom_qty': line.get('qty') or 1.0,
                'price_unit': line.get('price_unit') or 0.0,
                'tax_id': [(6, 0, line.get('tax_ids') or [])],
                'qb_line_id': qb_line_id,
            }

        if kind == 'discount':
            product = helpers.get_or_create_qb_discount_product()
            return {
                'name': line.get('name') or 'Discount',
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'price_unit': line.get('amount') or 0.0,
                'qb_line_id': qb_line_id,
            }

        if kind == 'shipping':
            product = helpers.get_or_create_qb_shipping_product()
            return {
                'name': line.get('name') or 'Shipping',
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'price_unit': line.get('amount') or 0.0,
                'qb_line_id': qb_line_id,
            }

        if kind == 'section':
            return {
                'display_type': 'line_section',
                'name': line.get('name') or 'Subtotal',
                'qb_line_id': qb_line_id,
            }

        if kind == 'note':
            return {
                'display_type': 'line_note',
                'name': line.get('name') or '',
                'qb_line_id': qb_line_id,
            }

        return None

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    def pull(self, client, config, job):
        if not self._check_model():
            return {}
        qb_data = self._fetch_estimate(client, job)
        if not qb_data:
            return {}
        return self._apply_pull(qb_data, config)

    def _fetch_estimate(self, client, job):
        if job.qb_entity_id:
            resp = client.read('Estimate', job.qb_entity_id)
            return resp.get('Estimate') or {}
        if job.odoo_record_id and 'sale.order' in self.env:
            order = self.env['sale.order'].browse(job.odoo_record_id)
            if order.exists() and order.qb_estimate_id:
                resp = client.read('Estimate', order.qb_estimate_id)
                return resp.get('Estimate') or {}
        return {}

    def _apply_pull(self, qb_data, config):
        vals = self._qb_estimate_to_odoo(qb_data, config)
        matcher = self.env['qb.record.matcher']
        SaleOrder = self.env['sale.order']

        existing = matcher.find_odoo_match('estimate', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'estimate', qb_data)
            lines = vals.pop('order_line', [])
            existing.with_context(skip_qb_sync=True).write(vals)
            if lines and existing.state in ('draft', 'sent'):
                existing.order_line.unlink()
                existing.with_context(skip_qb_sync=True).write({'order_line': lines})
        else:
            SaleOrder.with_context(skip_qb_sync=True).create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    # ------------------------------------------------------------------
    # Bulk
    # ------------------------------------------------------------------

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        for qb_data in client.query_all('Estimate', where_clause=where):
            try:
                self._apply_pull(qb_data, config)
            except Exception:
                _logger.exception(
                    'Failed to import QBO Estimate Id=%s',
                    qb_data.get('Id'),
                )

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
