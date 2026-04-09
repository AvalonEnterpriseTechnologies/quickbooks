# Miltech CRM Report

Custom Odoo 19 module that adds a live CRM dashboard and reporting tools for Miltech Manufacturing.

## Features

### Live Dashboard (CRM > Reporting > Miltech Dashboard)

- **KPI Cards** — Total Opportunities, Quoted Value, Quotes Won, Won Revenue, Quotes Lost, Engagements, and Orders Delivered
- **Pipeline by Stage** — Table showing every CRM stage with lead count, total revenue, and average probability. Click any row to jump to those leads.
- **Pipeline by Customer** — Table grouped by customer showing active opportunities, quoted value, won/lost counts, won value, and win rate. Excludes leads in the "Potential Clients" stage. Click any row to jump to that customer's leads.

### Filtering

- **Date presets** — Today, This Week, This Month buttons for quick filtering
- **Custom date range** — Manual start/end date pickers
- **Salesperson** — Filter by assigned salesperson
- **Customer** — Filter by customer/partner

### Date Logic

General metrics (Total Opportunities, Engagements, etc.) filter by **creation date**. Won metrics (Quotes Won, Won Revenue) filter by **date closed** — the date the deal was actually won — so clicking "Today" shows revenue won today regardless of when the lead was originally created.

### Won Stage Logic

A stage counts as "won" if Odoo's built-in `is_won` flag is set **or** the stage name is "Shipped" or "Delivered". This ensures delivered orders are included in won totals.

### Lost Stage Logic

The Lost KPI and per-customer lost counts are based on leads physically in the "Lost" stage, not on Odoo's archival mechanism.

### XLSX Export

Click the **Export XLSX** button to download a spreadsheet with three sheets:
1. **Dashboard** — All KPI values
2. **Pipeline by Stage** — Full stage breakdown
3. **Pipeline by Customer** — Full customer breakdown

### CRM View Enhancements

- **PO Number** (`x_studio_po_number`) column added to lead list, opportunity list, and lead form views
- **Has PO** computed boolean field available for filtering

## Technical Details

| Property     | Value                  |
| ------------ | ---------------------- |
| Version      | 19.0.1.0.0             |
| License      | LGPL-3                 |
| Dependencies | `crm`, `mail`          |
| Category     | Sales/CRM              |
| Application  | No (module extension)  |

### Module Structure

```
miltech_report/
├── __init__.py
├── __manifest__.py
├── README.md
├── controllers/
│   ├── __init__.py
│   └── report_controller.py          # /miltech/xlsx_report endpoint
├── models/
│   ├── __init__.py
│   ├── crm_lead.py                   # crm.lead inheritance (has_po field)
│   └── miltech_report.py             # miltech.report transient model (dashboard engine)
├── security/
│   └── ir.model.access.csv           # Access rights for salesman/manager groups
├── static/
│   └── src/
│       ├── js/
│       │   └── miltech_dashboard.js  # OWL frontend component
│       └── xml/
│           └── miltech_dashboard.xml # QWeb template for the dashboard UI
└── views/
    ├── crm_lead_views.xml            # Inherited CRM list/form views
    └── miltech_report_menu.xml       # Menu item + client action registration
```

### Models

- **`miltech.report`** (`TransientModel`) — Backend engine that builds search domains, computes KPIs, aggregates stage/customer data, and generates XLSX exports. Called from the OWL frontend via `orm.call()`.
- **`crm.lead`** (inherited) — Adds the computed `has_po` boolean field based on the Studio-created `x_studio_po_number` field.

### Frontend

The dashboard is an OWL component registered as a client action (`miltech_report.Dashboard`). It uses `useState` for reactivity, `useService('orm')` for backend communication, and `useService('action')` for navigation into standard CRM list views.

### Expected CRM Stages

The module references these stage names for specific KPI calculations:
- **Potential Clients** — Used for the Engagements count
- **Delivered** / **Shipped** — Used for Orders Delivered count and treated as won
- **Lost** — Used for the Quotes Lost count

All other stages are handled generically. If a referenced stage name doesn't exist, that KPI gracefully returns 0.

## Installation

### Odoo.sh

1. Push this module to a branch in your Odoo.sh repository
2. Go to **Apps** and click **Update Apps List**
3. Search for "Miltech CRM Report" and click **Install**

### Manual

1. Place the `miltech_report` folder in your Odoo addons path
2. Restart the Odoo server
3. Update the apps list and install from the Apps menu

## Prerequisites

- The `x_studio_po_number` field must exist on `crm.lead` (created via Odoo Studio or a data migration). The module includes safety checks and will not crash if the field is missing, but the Has PO feature will be non-functional.

## Access Rights

- **Sales / User (Own Documents)** — Full CRUD on the report wizard
- **Sales / Manager** — Full CRUD on the report wizard
