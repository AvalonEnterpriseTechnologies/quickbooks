# QuickBooks API Module for Odoo 19

Standalone QuickBooks Online connector for Odoo 19. Can be installed independently or alongside `slate_connector_v19`.

## Features

- **OAuth 2.0** connection to QuickBooks Online (sandbox + production)
- **Bidirectional sync**: customers, vendors, products, invoices, bills, payments, journal entries, credit memos, estimates, tax codes
- **Async queue** with cron-based processing, retry with exponential backoff
- **Conflict resolution**: last-modified, Odoo-wins, QBO-wins, or manual review
- **Configurable field mappings** per entity type
- **Webhook support**: CloudEvents and legacy Intuit format
- **Rate-limited API client**: sliding-window throttling at 450 req/min

## Installation

1. Place this module in your Odoo addons path
2. Update the module list: `Settings > Technical > Update Apps List`
3. Install **QuickBooks API Module**

### Dependencies

- Odoo 19 modules: `base`, `mail`, `account`, `product`, `contacts`
- Python: `requests` (`pip install requests`)
- Optional: `cryptography` for Fernet token encryption (`pip install cryptography`)

## Configuration

After installation, navigate to **QuickBooks > Configuration** to set up your Intuit app credentials and initiate the OAuth flow.

## Optional SLATE Integration

If `slate_connector_v19` is also installed, this module automatically:
- Registers as a provider in the SLATE integration registry
- Fires integration events on the SLATE event bus
- Extends the task sync manager for SLATE-initiated syncs
