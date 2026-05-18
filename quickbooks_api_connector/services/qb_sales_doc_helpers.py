"""Shared helpers for QBO sales-document pull mappers.

QuickBooks Online ships every sales transaction (Estimate, Invoice,
CreditMemo, SalesReceipt, RefundReceipt) with the same line-item grammar:

* ``SalesItemLineDetail`` — the regular item / quantity / unit-price row.
* ``GroupLineDetail`` — a bundle whose sub-lines are themselves
  ``SalesItemLineDetail`` rows. The group header carries the total but
  no line-level pricing of its own.
* ``DiscountLineDetail`` — a single percent- or amount-based discount
  applied to the rest of the document.
* ``ShippingLineDetail`` — a shipping/handling fee.
* ``SubTotalLineDetail`` — a visual subtotal marker emitted by QBO; no
  amount of its own.
* ``DescriptionOnly`` — a free-form note line that carries description
  text but no quantity / price.

Both the Estimate -> sale.order mapper and the Invoice / CreditMemo /
SalesReceipt / RefundReceipt -> account.move mapper need to handle every
one of these consistently so totals stay aligned with QBO and the
relinker can match Estimate lines to Invoice lines via ``Line.Id``.
This module centralises the parsing, the partner-address / payment-term
resolution, and the find-or-create of the placeholder "QB Discount" /
"QB Shipping" service products.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


QB_DISCOUNT_CODE = 'QB_DISCOUNT'
QB_SHIPPING_CODE = 'QB_SHIPPING'


class QBSalesDocHelpers(models.AbstractModel):
    _name = 'qb.sales.doc.helpers'
    _description = 'QuickBooks Sales Document Pull Helpers'

    # ------------------------------------------------------------------
    # Line parsing
    # ------------------------------------------------------------------

    @api.model
    def parse_qb_lines(self, qb_data, company=None):
        """Parse QBO ``Line`` array into a normalised list of dicts.

        Each returned dict has ``kind`` set to one of ``item``,
        ``discount``, ``shipping``, ``note``, or ``section``. Item
        rows expand ``GroupLineDetail`` parents into their sub-lines so
        callers never need to recurse.
        """
        parsed = []
        for qb_line in qb_data.get('Line') or []:
            parsed.extend(self._parse_one(qb_line, company))
        return parsed

    def _parse_one(self, qb_line, company):
        detail_type = qb_line.get('DetailType') or ''
        qb_line_id = str(qb_line.get('Id') or '')
        description = qb_line.get('Description') or ''
        amount = self._float(qb_line.get('Amount'))

        if detail_type == 'SalesItemLineDetail':
            detail = qb_line.get('SalesItemLineDetail') or {}
            return [self._item_dict(
                qb_line_id, description, amount, detail, company,
            )]

        if detail_type == 'GroupLineDetail':
            group = qb_line.get('GroupLineDetail') or {}
            sub_lines = []
            for sub in group.get('Line') or []:
                sub_lines.extend(self._parse_one(sub, company))
            if sub_lines:
                return sub_lines
            return [{
                'kind': 'note',
                'qb_line_id': qb_line_id,
                'name': description or 'Group line',
                'amount': amount,
            }]

        if detail_type == 'DiscountLineDetail':
            detail = qb_line.get('DiscountLineDetail') or {}
            return [{
                'kind': 'discount',
                'qb_line_id': qb_line_id,
                'name': description or 'Discount',
                'amount': -abs(amount) if amount else 0.0,
                'percent_based': bool(detail.get('PercentBased')),
                'discount_percent': self._float(detail.get('DiscountPercent')),
            }]

        if detail_type == 'ShippingLineDetail':
            return [{
                'kind': 'shipping',
                'qb_line_id': qb_line_id,
                'name': description or 'Shipping',
                'amount': amount or 0.0,
            }]

        if detail_type == 'SubTotalLineDetail':
            return [{
                'kind': 'section',
                'qb_line_id': qb_line_id,
                'name': description or 'Subtotal',
            }]

        if detail_type == 'DescriptionOnly':
            return [{
                'kind': 'note',
                'qb_line_id': qb_line_id,
                'name': description,
            }]

        if not detail_type:
            return []

        # Unknown / unsupported QBO line type — preserve as a note so totals
        # are not silently dropped and operators can audit the import.
        _logger.info('Unhandled QBO line DetailType=%s id=%s', detail_type, qb_line_id)
        return [{
            'kind': 'note',
            'qb_line_id': qb_line_id,
            'name': description or detail_type,
            'amount': amount,
        }]

    def _item_dict(self, qb_line_id, description, amount, detail, company):
        product = None
        item_ref = detail.get('ItemRef') or {}
        if item_ref.get('value'):
            domain = [('qb_item_id', '=', str(item_ref['value']))]
            if company and 'company_id' in self.env['product.product']._fields:
                domain += ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
            product = self.env['product.product'].search(domain, limit=1)

        tax_ids = []
        tax_ref = detail.get('TaxCodeRef') or {}
        if tax_ref.get('value'):
            tax_domain = [('qb_taxcode_id', '=', str(tax_ref['value']))]
            if company:
                tax_domain.append(('company_id', '=', company.id))
            tax = self.env['account.tax'].search(tax_domain, limit=1)
            if tax:
                tax_ids = tax.ids

        qty = self._float(detail.get('Qty')) or 1.0
        unit_price = self._float(detail.get('UnitPrice'))
        if unit_price is None and amount is not None and qty:
            unit_price = amount / qty
        unit_price = unit_price or 0.0

        return {
            'kind': 'item',
            'qb_line_id': qb_line_id,
            'name': description or (product.name if product else ''),
            'product_id': product.id if product else False,
            'qty': qty,
            'price_unit': unit_price,
            'amount': amount if amount is not None else qty * unit_price,
            'tax_ids': tax_ids,
            'service_date': detail.get('ServiceDate'),
        }

    # ------------------------------------------------------------------
    # Placeholder products
    # ------------------------------------------------------------------

    @api.model
    def get_or_create_qb_discount_product(self):
        return self._get_or_create_service_product(
            QB_DISCOUNT_CODE, 'QuickBooks Discount',
        )

    @api.model
    def get_or_create_qb_shipping_product(self):
        return self._get_or_create_service_product(
            QB_SHIPPING_CODE, 'QuickBooks Shipping & Handling',
        )

    def _get_or_create_service_product(self, default_code, name):
        Product = self.env['product.product']
        product = Product.search([('default_code', '=', default_code)], limit=1)
        if product:
            return product
        Product = Product.with_context(skip_qb_sync=True)
        vals = {
            'name': name,
            'default_code': default_code,
            'sale_ok': True,
            'purchase_ok': False,
            'type': 'service' if 'type' in Product._fields else 'consu',
        }
        return Product.create(vals)

    # ------------------------------------------------------------------
    # Partner / address resolution
    # ------------------------------------------------------------------

    @api.model
    def resolve_partner_id(self, qb_data, company=None):
        """Return the Odoo partner id matching the QBO CustomerRef, or False."""
        customer_ref = qb_data.get('CustomerRef') or {}
        if not customer_ref.get('value'):
            return False
        partner = self.env['res.partner'].search([
            ('qb_customer_id', '=', str(customer_ref['value'])),
        ], limit=1)
        return partner.id if partner else False

    @api.model
    def resolve_address_partner(self, parent_partner, qb_addr, addr_type):
        """Return a partner suitable for ``partner_invoice_id`` / ``partner_shipping_id``.

        Strategy:

        * If ``qb_addr`` is empty or matches the parent partner's primary
          address, return the parent itself (Odoo will inherit).
        * Otherwise search the parent's children for an address-only
          contact matching the QBO address (street + city + zip + country).
        * If none exists, create a child contact of ``type='invoice'`` or
          ``type='delivery'`` so the SO / Invoice can point at it.

        This is intentionally conservative: a historical import should
        not pollute the contact tree with hundreds of near-duplicate
        children. We only create a child when the QBO address materially
        differs from the parent's.
        """
        if not parent_partner or not qb_addr:
            return parent_partner.id if parent_partner else False

        normalized = self._normalize_address_fields(qb_addr)
        if not normalized:
            return parent_partner.id

        parent_norm = self._partner_address_signature(parent_partner)
        new_norm = self._qb_address_signature(qb_addr)
        if parent_norm == new_norm:
            return parent_partner.id

        for child in parent_partner.child_ids:
            if self._partner_address_signature(child) == new_norm:
                return child.id

        Partner = self.env['res.partner'].with_context(skip_qb_sync=True)
        child = Partner.create({
            'parent_id': parent_partner.id,
            'type': 'invoice' if addr_type == 'invoice' else 'delivery',
            'name': parent_partner.name,
            **normalized,
        })
        return child.id

    def _normalize_address_fields(self, qb_addr):
        vals = {}
        if qb_addr.get('Line1'):
            vals['street'] = qb_addr['Line1']
        if qb_addr.get('Line2'):
            vals['street2'] = qb_addr['Line2']
        if qb_addr.get('City'):
            vals['city'] = qb_addr['City']
        if qb_addr.get('PostalCode'):
            vals['zip'] = qb_addr['PostalCode']
        if qb_addr.get('CountrySubDivisionCode'):
            state = self.env['res.country.state'].search([
                ('code', '=', qb_addr['CountrySubDivisionCode']),
            ], limit=1)
            if state:
                vals['state_id'] = state.id
        if qb_addr.get('Country'):
            country = self.env['res.country'].search([
                ('code', '=', qb_addr['Country']),
            ], limit=1)
            if country:
                vals['country_id'] = country.id
        return vals

    @staticmethod
    def _partner_address_signature(partner):
        if not partner:
            return ()
        return (
            (partner.street or '').strip().casefold(),
            (partner.street2 or '').strip().casefold(),
            (partner.city or '').strip().casefold(),
            (partner.zip or '').strip().casefold(),
            partner.state_id.id if partner.state_id else 0,
            partner.country_id.id if partner.country_id else 0,
        )

    def _qb_address_signature(self, qb_addr):
        state_id = 0
        if qb_addr.get('CountrySubDivisionCode'):
            state = self.env['res.country.state'].search([
                ('code', '=', qb_addr['CountrySubDivisionCode']),
            ], limit=1)
            state_id = state.id if state else 0
        country_id = 0
        if qb_addr.get('Country'):
            country = self.env['res.country'].search([
                ('code', '=', qb_addr['Country']),
            ], limit=1)
            country_id = country.id if country else 0
        return (
            (qb_addr.get('Line1') or '').strip().casefold(),
            (qb_addr.get('Line2') or '').strip().casefold(),
            (qb_addr.get('City') or '').strip().casefold(),
            (qb_addr.get('PostalCode') or '').strip().casefold(),
            state_id,
            country_id,
        )

    # ------------------------------------------------------------------
    # Payment terms
    # ------------------------------------------------------------------

    @api.model
    def resolve_payment_term_id(self, qb_data):
        ref = qb_data.get('SalesTermRef') or {}
        if not ref.get('value'):
            return False
        term = self.env['account.payment.term'].search([
            ('qb_term_id', '=', str(ref['value'])),
        ], limit=1)
        return term.id if term else False

    # ------------------------------------------------------------------
    # LinkedTxn
    # ------------------------------------------------------------------

    @api.model
    def collect_linked_txns(self, qb_data, txn_type):
        """Return [(qb_id, full_dict), ...] for LinkedTxn entries of ``txn_type``."""
        out = []
        for entry in qb_data.get('LinkedTxn') or []:
            if entry.get('TxnType') != txn_type:
                continue
            qb_id = str(entry.get('TxnId') or '')
            if qb_id:
                out.append((qb_id, entry))
        return out

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _float(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
