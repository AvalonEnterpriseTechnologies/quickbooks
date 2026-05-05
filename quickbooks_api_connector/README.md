# QuickBooks API Module for Odoo 19

Standalone QuickBooks Online connector for Odoo 19. Can be installed independently or alongside `slate_connector_v19`.

## Features

- **OAuth 2.0** connection to QuickBooks Online (sandbox + production)
- **One-time setup wizard** for Intuit app credentials, followed by a sync-only settings panel
- **Bidirectional sync**: customers, vendors, products, invoices, bills, payments, journal entries, credit memos, estimates, vendor credits, purchase orders, expenses, sales receipts, refund receipts, deposits, transfers, classes, departments, employees, time activities, attachments, payment terms, and tax codes where QBO permits writes
- **Async queue** with cron-based processing, retry with exponential backoff
- **Conflict resolution**: last-modified, Odoo-wins, QBO-wins, or manual review
- **Configurable field mappings** per entity type
- **Webhook support**: CloudEvents and legacy Intuit format
- **Rate-limited API client**: sliding-window throttling at 450 req/min
- **CDC incremental sync** for supported QBO entities after the first successful sync

## Installation

1. Place this module in your Odoo addons path
2. Update the module list: `Settings > Technical > Update Apps List`
3. Install **QuickBooks API Module**

### Dependencies

- Odoo 19 modules: `base`, `mail`, `account`, `product`, `contacts`
- Python: `requests` (`pip install requests`)
- Optional: `cryptography` for Fernet token encryption (`pip install cryptography`)

## Configuration

After installation, open **QuickBooks > Sync** or **Settings > QuickBooks**.
If credentials are not configured, Odoo opens the one-time setup wizard. Enter:

- Intuit Client ID
- Intuit Client Secret
- Sandbox or Production environment
- Optional webhook verifier token

After OAuth succeeds, the regular settings page is intentionally minimal: it
shows connection status, the last sync timestamp, **Connect**, **Sync Now**, and
**Disconnect**. Advanced credentials, sync toggles, and troubleshooting records
remain available to managers under **Settings > Technical > QuickBooks**.

## Intuit App Setup

Configure these redirect/webhook URLs in your Intuit Developer app:

- OAuth redirect URI: `https://<your-odoo-domain>/qb/oauth/callback`
- Webhook endpoint: `https://<your-odoo-domain>/qb/webhook`

The accounting scope is always requested. Payroll compensation and QuickBooks
Time scopes are requested only when those advanced features are enabled.

## Migration

Use the Initial Migration wizard after OAuth is connected. See
[`docs/migration.md`](../docs/migration.md) for recommended ordering and checks.

## Troubleshooting

- **Connection errors**: reconnect from Settings > QuickBooks.
- **Token refresh failures**: verify the Intuit app credentials in the Technical configuration.
- **Sync conflicts**: review `quickbooks.sync.queue` records with state `conflict`.
- **Rate limits**: the API client throttles per QBO realm and retries 429/5xx responses.

## Optional SLATE Integration

If `slate_connector_v19` is also installed, this module automatically:
- Registers as a provider in the SLATE integration registry
- Fires integration events on the SLATE event bus
- Extends the task sync manager for SLATE-initiated syncs
