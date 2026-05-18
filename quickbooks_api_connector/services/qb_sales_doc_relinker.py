"""Second-pass relinker for QBO sales-document parent / child links.

During a historical pull QBO records can land out of order: an Invoice
may be created in Odoo before its parent Estimate has been imported, or
a CreditMemo before the Invoice it reverses. The per-record pull
mappers stash the raw QBO ``LinkedTxn`` ids on the Odoo record
(``qb_source_estimate_qb_id`` / ``qb_source_invoice_qb_id`` /
``qb_source_creditmemo_qb_id``), but they cannot always resolve those
ids to live Odoo records the first time around.

``qb.sales.doc.relinker.relink_all`` walks every Odoo sales record that
still has an unresolved QBO parent reference, resolves it now that the
full sales chain has been imported, and additionally rebuilds line-level
``account.move.line.sale_line_ids`` so Odoo's "Invoiced / To invoice"
reporting works on imported records.

It also writes structured counters back to
``quickbooks.migration.run.step`` so the Settings panel data-integrity
block can show, per sales-doc type: imported / linked / orphan / QBO
total / Odoo total.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


SALES_DOC_ENTITY_TYPES = (
    'estimate', 'invoice', 'credit_memo',
    'sales_receipt', 'refund_receipt',
)


class QBSalesDocRelinker(models.AbstractModel):
    _name = 'qb.sales.doc.relinker'
    _description = 'QuickBooks Sales-Document Relinker (second pass)'

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @api.model
    def relink_all(self, config, run=None):
        """Run every relink pass and return a per-entity counters dict.

        ``run`` is an optional ``quickbooks.migration.run`` whose
        ``step_ids`` will receive the counters (matched by
        ``entity_type``). The counters dict is shaped::

            {
              'estimate':      {'imported': N, 'linked': N, 'orphan': N,
                                'amount_total_qbo': X, 'amount_total_odoo': Y},
              'invoice':       {...},
              'credit_memo':   {...},
              'sales_receipt': {...},
              'refund_receipt':{...},
            }
        """
        counters = {entity: self._empty_counters() for entity in SALES_DOC_ENTITY_TYPES}

        counters['estimate'].update(self._sum_estimates(config))
        counters['invoice'].update(self.relink_invoices_to_estimates(config))
        counters['credit_memo'].update(self.relink_credit_memos(config))
        counters['refund_receipt'].update(self.relink_refund_receipts(config))
        counters['sales_receipt'].update(self._sum_sales_receipts(config))

        if run:
            self._write_step_counters(run, counters)
        return counters

    # ------------------------------------------------------------------
    # Estimate (no LinkedTxn to walk; counters only)
    # ------------------------------------------------------------------

    def _sum_estimates(self, config):
        if 'sale.order' not in self.env:
            return {'imported': 0, 'linked': 0, 'orphan': 0,
                    'amount_total_qbo': 0.0, 'amount_total_odoo': 0.0}
        orders = self.env['sale.order'].search([
            ('qb_estimate_id', '!=', False),
            ('company_id', '=', config.company_id.id),
        ])
        amount_odoo = sum(orders.mapped('amount_total'))
        amount_qbo = sum(self._raw_total(o.qb_raw_json) for o in orders)
        return {
            'imported': len(orders),
            'linked': len(orders),
            'orphan': 0,
            'amount_total_qbo': amount_qbo,
            'amount_total_odoo': amount_odoo,
        }

    # ------------------------------------------------------------------
    # Invoice -> Estimate linkage
    # ------------------------------------------------------------------

    @api.model
    def relink_invoices_to_estimates(self, config):
        counters = self._empty_counters()
        Move = self.env['account.move']
        if 'qb_source_estimate_qb_id' not in Move._fields:
            return counters
        if 'sale.order' not in self.env:
            return counters

        invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('qb_invoice_id', '!=', False),
            ('company_id', '=', config.company_id.id),
        ])
        counters['imported'] = len(invoices)
        counters['amount_total_odoo'] = sum(invoices.mapped('amount_total'))
        counters['amount_total_qbo'] = sum(
            self._raw_total(m.qb_raw_json) for m in invoices
        )

        for move in invoices:
            qb_estimate_id = move.qb_source_estimate_qb_id
            if not qb_estimate_id:
                if move.qb_source_sale_order_id:
                    counters['linked'] += 1
                continue
            sale_order = self.env['sale.order'].search([
                ('qb_estimate_id', '=', qb_estimate_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)
            if not sale_order:
                counters['orphan'] += 1
                continue
            if move.qb_source_sale_order_id != sale_order:
                move.with_context(skip_qb_sync=True).write({
                    'qb_source_sale_order_id': sale_order.id,
                    'invoice_origin': move.invoice_origin or sale_order.name,
                })
            self._link_lines_to_so(move, sale_order)
            counters['linked'] += 1
        return counters

    def _link_lines_to_so(self, move, sale_order):
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
            qb_line_id = inv_line.qb_line_id
            if not qb_line_id:
                continue
            so_line = so_lines_by_qb.get(qb_line_id)
            if not so_line:
                continue
            if 'sale_line_ids' not in inv_line._fields:
                continue
            current = inv_line.sale_line_ids.ids
            if so_line.id in current:
                continue
            inv_line.with_context(skip_qb_sync=True).write({
                'sale_line_ids': [(4, so_line.id)],
            })

    # ------------------------------------------------------------------
    # CreditMemo -> Invoice linkage
    # ------------------------------------------------------------------

    @api.model
    def relink_credit_memos(self, config):
        counters = self._empty_counters()
        Move = self.env['account.move']
        if 'qb_source_invoice_qb_id' not in Move._fields:
            return counters

        credit_memos = Move.search([
            ('move_type', '=', 'out_refund'),
            ('qb_creditmemo_id', '!=', False),
            ('company_id', '=', config.company_id.id),
        ])
        counters['imported'] = len(credit_memos)
        counters['amount_total_odoo'] = sum(credit_memos.mapped('amount_total'))
        counters['amount_total_qbo'] = sum(
            self._raw_total(m.qb_raw_json) for m in credit_memos
        )

        for cm in credit_memos:
            qb_invoice_id = cm.qb_source_invoice_qb_id
            if not qb_invoice_id:
                if cm.reversed_entry_id:
                    counters['linked'] += 1
                continue
            source = Move.search([
                ('qb_invoice_id', '=', qb_invoice_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)
            if not source:
                counters['orphan'] += 1
                continue
            if cm.reversed_entry_id != source:
                cm.with_context(skip_qb_sync=True).write({
                    'reversed_entry_id': source.id,
                })
            counters['linked'] += 1
        return counters

    # ------------------------------------------------------------------
    # RefundReceipt -> CreditMemo linkage
    # ------------------------------------------------------------------

    @api.model
    def relink_refund_receipts(self, config):
        counters = self._empty_counters()
        Move = self.env['account.move']
        if 'qb_source_creditmemo_qb_id' not in Move._fields:
            return counters

        refunds = Move.search([
            ('move_type', '=', 'out_refund'),
            ('qb_refundreceipt_id', '!=', False),
            ('company_id', '=', config.company_id.id),
        ])
        counters['imported'] = len(refunds)
        counters['amount_total_odoo'] = sum(refunds.mapped('amount_total'))
        counters['amount_total_qbo'] = sum(
            self._raw_total(m.qb_raw_json) for m in refunds
        )

        for rr in refunds:
            qb_cm_id = rr.qb_source_creditmemo_qb_id
            if not qb_cm_id:
                if rr.reversed_entry_id:
                    counters['linked'] += 1
                continue
            source = Move.search([
                ('qb_creditmemo_id', '=', qb_cm_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)
            if not source:
                counters['orphan'] += 1
                continue
            if rr.reversed_entry_id != source:
                rr.with_context(skip_qb_sync=True).write({
                    'reversed_entry_id': source.id,
                })
            counters['linked'] += 1
        return counters

    # ------------------------------------------------------------------
    # SalesReceipt counters (no LinkedTxn semantics — informational only)
    # ------------------------------------------------------------------

    def _sum_sales_receipts(self, config):
        Move = self.env['account.move']
        if 'qb_salesreceipt_id' not in Move._fields:
            return self._empty_counters()
        moves = Move.search([
            ('qb_salesreceipt_id', '!=', False),
            ('company_id', '=', config.company_id.id),
        ])
        return {
            'imported': len(moves),
            'linked': len(moves),
            'orphan': 0,
            'amount_total_qbo': sum(self._raw_total(m.qb_raw_json) for m in moves),
            'amount_total_odoo': sum(moves.mapped('amount_total')),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_counters():
        return {
            'imported': 0,
            'linked': 0,
            'orphan': 0,
            'amount_total_qbo': 0.0,
            'amount_total_odoo': 0.0,
        }

    @staticmethod
    def _raw_total(raw_json):
        if not raw_json or not isinstance(raw_json, dict):
            return 0.0
        try:
            return float(raw_json.get('TotalAmt') or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _write_step_counters(self, run, counters):
        Step = self.env['quickbooks.migration.run.step']
        for entity, c in counters.items():
            step = Step.search([
                ('run_id', '=', run.id),
                ('entity_type', '=', entity),
                ('direction', '=', 'pull'),
            ], limit=1, order='id desc')
            if not step:
                step = Step.create({
                    'run_id': run.id,
                    'entity_type': entity,
                    'direction': 'pull',
                    'status': 'completed',
                    'sequence': 200,
                })
            step.write({
                'actual_count': c['imported'],
                'linked_count': c['linked'],
                'orphan_link_count': c['orphan'],
                'amount_total_qbo': c['amount_total_qbo'],
                'amount_total_odoo': c['amount_total_odoo'],
            })
