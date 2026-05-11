# QuickBooks to Odoo Balance Sync Audit

This audit reviews the balance-related surface of the QuickBooks API connector and identifies what is currently transferred, what is only stored as a reference snapshot, and what needs additional reconciliation support.

## Summary

The connector imports accounting documents and selected QBO financial reports, but before this remediation it did not provide complete point-in-time balance parity checks. Account balances were mostly represented through `BalanceSheet` and `TrialBalance` snapshots in `quickbooks.account.balance`, while AR/AP aging, inventory valuation, sales tax liabilities, and Odoo-vs-QBO variance tracking were missing.

## Current Coverage And Gaps

### Customer Balances / AR Aging

Invoices, credit memos, and payments are synced as transactions, but AR aging balances were not pulled from QBO report endpoints. `services/sync_reports.py` previously listed only `BalanceSheet`, `ProfitAndLoss`, `TrialBalance`, `GeneralLedger`, and `WorkersCompensation` in `REPORT_TYPES`.

Impact: Odoo could derive receivables from imported transactions, but there was no QBO aging snapshot to prove bucket-level parity or identify old balances not represented by synced transactions.

Remediation: add `AgedReceivables` and `AgedReceivableDetail`, store rows in `quickbooks.partner.balance`, and reconcile them against Odoo receivable move lines.

### Vendor Balances / AP Aging

Bills, vendor credits, and bill payments are synced as transactions. AP aging had the same gap as AR aging: no QBO aging snapshot and no bucket-level comparison.

Remediation: add `AgedPayables` and `AgedPayableDetail`, store rows in `quickbooks.partner.balance`, and reconcile them against Odoo payable move lines.

### Bank And Credit Card Balances

`services/sync_accounts.py` stores `CurrentBalance` and `CurrentBalanceWithSubAccounts` on `account.account` as `qb_current_balance` and `qb_current_balance_with_subaccounts`. These are current QBO account attributes, not historical balance snapshots.

Impact: the connector could show the latest QBO balance, but could not verify a bank or credit card balance as of a migration cutoff date unless the Balance Sheet or Trial Balance snapshot was inspected separately.

Remediation: keep the account fields, use Balance Sheet / Trial Balance snapshots for period-end account balances, and include those rows in the variance engine.

### Inventory / Stock Valuation

`services/sync_products.py` imports item metadata and can update `stock.quant.quantity` from `QtyOnHand`. It does not import QBO's inventory valuation reports.

Impact: quantity could be aligned while valuation drift remained invisible, especially where QBO average cost and Odoo `standard_price` differ.

Remediation: add `InventoryValuationSummary`, store per-product quantities and values in `quickbooks.inventory.balance`, and reconcile those rows against Odoo stock valuation estimates.

### General Ledger

The connector imports `GeneralLedger` as hierarchical report rows, but the previous `_store_journal_balances` logic treated generic row amounts as journal totals. QBO GL rows use a wider column layout, so the derived journal totals were not reliable.

Remediation: keep raw hierarchical GL rows for review, stop treating generic GL row amounts as authoritative journal balances, and rely on the new variance engine for account-level reconciliation.

### Trial Balance

Trial Balance rows were stored as `quickbooks.account.balance` and used to post opening balances. The previous account lookup fell back to plain account name matching, which could mis-link similarly named accounts.

Remediation: route report row matching through `qb.record.matcher.find_odoo_match_for_account`, support Accrual/Cash/both report pulls, add configurable report windows, and skip computed total/section rows from account balance rows.

### Opening / Beginning Balances

`wizards/qb_post_opening_balances_wizard.py` posted Trial Balance rows into a single opening journal entry. Unmatched rows were skipped and the delta was offset to Opening Balance Equity, which could hide incomplete account mapping. Income and expense balances were also posted directly rather than rolled into retained earnings.

Remediation: fail on unmatched rows unless explicitly allowed, split balance sheet accounts from P&L accounts, roll P&L into retained earnings, default the posting date to the snapshot period end, and optionally lock the company through the opening date.

### Tax Liabilities And Retained Earnings

Tax codes sync from QBO, but sales tax liability balances were not imported. QBO `RetainedEarnings` was mapped to Odoo `equity`; it should map to `equity_unaffected` for Odoo retained earnings behavior.

Remediation: add `SalesTaxLiabilityReport`, store rows in `quickbooks.tax.liability`, reclassify QBO retained earnings to `equity_unaffected`, and add a migration for already-linked retained earnings accounts.

### Multi-Currency

Transaction mappers read `CurrencyRef` but did not persist QBO `ExchangeRate` or home-currency totals. That means Odoo could recompute amounts using its current rates and drift from QBO's transaction-specific exchange rates.

Remediation: capture QBO exchange rate and home total on moves/payments, apply currency context where possible, and document exchange-rate direction in the exchange-rate sync service.

### Cutoff Dates

Report pulls previously ended at `fields.Date.context_today()` and were chunked in six-month windows. That was useful for history, but insufficient for migration cutoff verification.

Remediation: add a report window strategy and use snapshot period end consistently in opening-balance posting and reconciliation.

## Residual Limitations

Some QBO reports expose presentation rows without durable entity IDs. Where a row lacks a QBO account, partner, product, or tax identifier, the connector falls back to normalized names and records any unmatched variance so users can correct mappings instead of silently accepting incomplete balances.

Inventory valuation reconciliation estimates Odoo value from stock quantities and product cost unless stock valuation layers are available in the installed Odoo edition and configuration.
