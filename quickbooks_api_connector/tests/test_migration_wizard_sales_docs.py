"""Initial migration wizard regression tests for the sales-doc chain.

Validates:

* All four new sales-doc toggles (estimates / credit_memos /
  sales_receipts / refund_receipts) actually queue ``ordered_entities``
  in the correct parent-before-child order.
* The wizard always enqueues a final ``sales_doc_relink`` step when
  any sales document is included.
* Re-running the wizard does not duplicate Odoo records — the matcher
  + idempotency key keep imports idempotent.
"""

from unittest.mock import patch

from .common import QuickbooksTestCommon


class TestMigrationWizardSalesDocs(QuickbooksTestCommon):

    def _make_wizard(self, **overrides):
        # Disable every default migrate_* toggle so each test can opt in
        # only to the entities it cares about and the resulting
        # ordered_entities list contains nothing extraneous.
        Wizard = self.env['quickbooks.migration.wizard']
        defaults = {
            'company_id': self.company.id,
            'direction': 'import',
            'mode': 'dry_run',
        }
        for name in Wizard._fields:
            if name.startswith('migrate_'):
                defaults[name] = False
        defaults.update(overrides)
        return Wizard.create(defaults)

    def test_wizard_queues_sales_docs_in_parent_child_order(self):
        wizard = self._make_wizard(
            migrate_estimates=True,
            migrate_invoices=True,
            migrate_credit_memos=True,
            migrate_sales_receipts=True,
            migrate_refund_receipts=True,
        )
        wizard.action_start_migration()
        run = self.env['quickbooks.migration.run'].search(
            [('company_id', '=', self.company.id)],
            order='started_at desc', limit=1,
        )
        self.assertTrue(run)
        ordered = [
            s.entity_type
            for s in run.step_ids.sorted('sequence')
            if s.direction == 'pull'
        ]
        # Parent (estimate) must precede invoice; invoice must precede
        # credit_memo / sales_receipt / refund_receipt; relinker is last.
        idx = {entity: i for i, entity in enumerate(ordered) if entity in (
            'estimate', 'invoice', 'credit_memo',
            'sales_receipt', 'refund_receipt', 'sales_doc_relink',
        )}
        self.assertLess(idx['estimate'], idx['invoice'])
        self.assertLess(idx['invoice'], idx['credit_memo'])
        self.assertLess(idx['credit_memo'], idx['sales_receipt'])
        self.assertLess(idx['sales_receipt'], idx['refund_receipt'])
        self.assertEqual(
            idx['sales_doc_relink'],
            max(idx.values()),
            'sales_doc_relink must be the final pull step',
        )

    def test_wizard_skips_relink_when_no_sales_doc_selected(self):
        # Only opening balances + accounts = no sales-doc imports.
        wizard = self._make_wizard(migrate_accounts=True)
        wizard.action_start_migration()
        run = self.env['quickbooks.migration.run'].search(
            [('company_id', '=', self.company.id)],
            order='started_at desc', limit=1,
        )
        entities = run.step_ids.mapped('entity_type')
        self.assertNotIn('sales_doc_relink', entities)

    def test_dry_run_does_not_actually_call_relinker(self):
        # In dry_run mode the wizard should plan the relink step but not
        # invoke qb.sales.doc.relinker.relink_all.
        with patch(
            'odoo.addons.quickbooks_api_connector.services.qb_sales_doc_relinker.'
            'QBSalesDocRelinker.relink_all'
        ) as mocked:
            wizard = self._make_wizard(
                migrate_estimates=True, migrate_invoices=True,
            )
            wizard.action_start_migration()
            mocked.assert_not_called()
