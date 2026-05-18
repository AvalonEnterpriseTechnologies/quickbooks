from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    qb_source_sale_order_id = fields.Many2one(
        'sale.order',
        string='QB Source Estimate (Odoo SO)',
        index=True,
        copy=False,
        help='Odoo sale.order resolved from the QBO Estimate referenced by '
             'this Invoice / CreditMemo via LinkedTxn. Populated by the QBO '
             'pull and the qb.sales.doc.relinker second-pass service.',
    )
    qb_source_estimate_qb_id = fields.Char(
        string='QB Source Estimate Id',
        index=True,
        copy=False,
        help='Raw QuickBooks Online Estimate Id captured from this record\'s '
             'LinkedTxn array. Stored even when the Odoo Estimate has not yet '
             'been imported, so the relinker can rebuild the link later.',
    )
    qb_source_invoice_qb_id = fields.Char(
        string='QB Source Invoice Id',
        index=True,
        copy=False,
        help='Raw QuickBooks Online Invoice Id captured from a CreditMemo\'s '
             'LinkedTxn array, used to rebuild the Invoice -> CreditMemo '
             'reversal link.',
    )
    qb_source_creditmemo_qb_id = fields.Char(
        string='QB Source CreditMemo Id',
        index=True,
        copy=False,
        help='Raw QuickBooks Online CreditMemo Id captured from a '
             'RefundReceipt\'s LinkedTxn array, used to rebuild the '
             'CreditMemo -> RefundReceipt link.',
    )
    qb_doc_number = fields.Char(
        string='QB DocNumber',
        index=True,
        copy=False,
        help='QuickBooks Online DocNumber as displayed in QBO. Kept '
             'alongside Odoo\'s own sequence so reconciliation reports can '
             'match the QBO document number even when Odoo re-numbers the '
             'record.',
    )
