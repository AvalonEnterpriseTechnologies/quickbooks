# QuickBooks Initial Migration

Use the Initial Migration wizard after the one-time QuickBooks setup wizard has
completed OAuth and the configuration shows as connected.

## Recommended Order

1. Import from QuickBooks first.
2. Sync chart of accounts, tax codes, terms, classes, departments, customers,
   vendors, employees, products, and inventory quantities.
3. Sync transaction records: estimates, invoices, bills, payments, journal
   entries, sales receipts, refund receipts, vendor credits, deposits, and
   transfers.
4. Run `Sync Now` from Settings > QuickBooks after the migration queue drains.

The wizard queues work into `quickbooks.sync.queue`; the queue processor cron
handles retries and conflict states.

## Verification

After migration, compare record counts between the QBO sandbox company and Odoo
for customers, vendors, products, invoices, bills, and payments. Review
`QuickBooks > Sync Logs` for any warning or error entries before enabling
periodic sync in production.
