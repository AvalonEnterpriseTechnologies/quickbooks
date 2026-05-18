{
    'name': 'QuickBooks API Connector — Sale Bridge',
    'version': '19.0.2.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Estimate <-> Sale Order linkage and Invoice cross-references',
    'description': """
        Bridge module that wires QuickBooks Online sales-document sync into
        Odoo's Sales module. Auto-installed when both
        ``quickbooks_api_connector`` and ``sale`` are installed; safely
        absent otherwise.

        On top of the base ``qb_estimate_id`` linkage shipped in 1.0, this
        version adds the schema required by the historical sales-document
        migration:

          * ``sale.order.qb_doc_number`` and ``sale.order.qb_invoice_ids``
            so each Odoo SO surfaces its QBO DocNumber and the Invoices
            QBO records as derived from it.
          * ``sale.order.line.qb_line_id`` and
            ``account.move.line.qb_line_id`` so per-line links between
            Estimate lines and Invoice lines can be rebuilt by the
            ``qb.sales.doc.relinker`` second-pass service.
          * ``account.move.qb_source_sale_order_id``,
            ``account.move.qb_source_estimate_qb_id``,
            ``account.move.qb_source_invoice_qb_id``,
            ``account.move.qb_source_creditmemo_qb_id``, and
            ``account.move.qb_doc_number`` so QBO LinkedTxn relationships
            (Estimate -> Invoice -> CreditMemo -> RefundReceipt) survive
            the historical pull even when child documents land before
            their parents.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'sale', 'account'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
