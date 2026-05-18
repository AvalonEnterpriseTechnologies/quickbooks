# QuickBooks Payroll -> Odoo Payroll Cutover

This runbook walks an admin through migrating a US (Kansas-first) company from
QuickBooks Online Payroll to Odoo `hr_payroll`, with QuickBooks left in place as
a sealed read-only archive. Tested against the QBO Online Payroll product
(Core / Premium / Elite) with the GraphQL Payroll API entitled on the Intuit
developer app.

The relevant modules in this repo:

- `quickbooks_api_connector` - core connector, scopes, sync engine, cron, settings UI
- `quickbooks_api_connector_hr` - bridge fields on `hr.employee` / `hr.work.location`
- `quickbooks_api_connector_hr_payroll` - bridge fields on `hr.contract`, `hr.payslip`, `hr.payroll.structure`, `hr.salary.rule`, plus the `qb.payroll.check` archive
- `l10n_us_hr_payroll_ks` - Kansas K-4 + KS_SIT salary rule

## 1. One-time Intuit setup

In the Intuit Developer dashboard for the app that backs this connector, add
the following OAuth scopes:

- `com.intuit.quickbooks.accounting` (already required)
- `payroll.compensation.read`
- `payroll.employee.read`
- `payroll.taxes.read`

The connector's `qb.auth.service._get_scopes` adds these three payroll scopes
automatically once `payroll_enabled` is set on the company's
`quickbooks.config`. The next OAuth handshake will re-prompt the user for
consent.

## 2. Install + flip the bridge

In Odoo:

1. Install `hr`, `hr_contract`, `hr_payroll`, and `l10n_us_hr_payroll`. On a
   Kansas company also install `l10n_us_hr_payroll_ks`.
2. Install `quickbooks_api_connector` and `quickbooks_api_connector_hr`. The
   contact-level employee bridge auto-installs once `hr` is present.
3. **(Enterprise only)** Open
   `quickbooks_api_connector_hr_payroll/__manifest__.py` and set both
   `installable` and `auto_install` to `True`, then restart Odoo with
   `-u quickbooks_api_connector`. The bridge ships with `installable=False`
   so Community deployments (or Enterprise images that do not load
   `hr_contract`) are not broken by an attempted install. The `post_init_hook`
   seeds the payroll data for every connected, payroll-enabled company on
   the first install.
4. `Settings > QuickBooks` > tick **Enable Payroll Sync**. Per-entity toggles
   (Pay Schedules, Pay Items, Payroll Employees, Tax Setup, Compensations,
   Checks history) appear under it; defaults are sensible.
5. Re-run **Connect to QuickBooks** so Intuit returns the broader payroll
   scopes.

## 3. Initial migration

From `Settings > QuickBooks` click **Run Initial Migration**. The migration
wizard (`quickbooks.migration.wizard`) walks every entity in dependency order.
The payroll portion runs:

1. `payroll_settings` - workers-comp classes, etc.
2. `work_location` - REST `EmployeeWorkLocation` -> `hr.work.location`
3. `payroll_schedule` - GraphQL `payrollPaySchedules` -> `hr.payroll.structure` (find-or-create per QBO schedule, with a parent `hr.payroll.structure.type` per frequency)
4. `payroll_pay_item` - GraphQL `payrollPayItems` -> `hr.salary.rule` (one rule per pay item per structure, with category, GL debit, GL credit, vendor)
5. `payroll_employee` - GraphQL `payrollEmployees` -> `hr.employee` bridge fields, mailing address as `res.partner`, contract upsert with `wage`, `wage_type`, `schedule_pay`, `structure_type_id`, `resource_calendar_id`
6. `payroll_tax_setup` - GraphQL `payrollEmployeeTaxSetup` -> federal W-4 fields plus `qb_state_w4_json`. Kansas employees additionally get `l10n_ks_filing_status`, `l10n_ks_total_allowances`, `l10n_ks_additional_withholding`, `l10n_ks_exempt`, `l10n_ks_form_effective_date`.
7. `payroll_compensation` - GraphQL `payrollEmployeeCompensations` -> contract `wage` / `qb_rate` / `qb_rate_type`
8. `payroll_check` - GraphQL `payrollChecks` -> `qb.payroll.check` archive with `qb.payroll.check.line` rows for earnings / taxes (employee + employer split) / deductions / employer contributions
9. `employee_benefit` - benefit lines attached to the matching archive check as `line_type = 'benefit'`

The daily cron `ir_cron_qb_payroll_full` (`qb.sync.payroll.orchestrator`)
repeats the same walk in dependency order. It skips checks + benefits for
companies whose payroll has been cut over.

## 4. Pre-cutover audit

From `Settings > QuickBooks > QuickBooks Payroll` click **Pre-Cutover Audit**
before the live cutover. The audit posts a chatter summary on
`quickbooks.config` listing:

- **Blocking employees**: missing contract, missing `wage_type` / `schedule_pay`
  / `structure_type_id` / `resource_calendar_id`, missing mailing address /
  state, missing federal W-4, missing Kansas K-4 (for KS workers).
- **Blocking structures**: missing `type_id` or no salary rules.
- **Warnings**: contracts with `wage = 0`, etc.

Fix each blocker and re-run the audit until it returns clean.

## 5. Cutover

Click **Cutover To Odoo Payroll**. The connector re-runs the audit. If it is
clean it:

1. Writes `qb_payroll_archived = True` and `qb_payroll_cutover_date = now` on
   `quickbooks.config`.
2. Attaches the Kansas `KS_SIT` salary rule to every US-country payroll
   structure (reusing the helper from
   `l10n_us_hr_payroll_ks/hooks.py::_create_salary_rule`).
3. Suppresses the daily payroll-check / benefit pulls for this company. The
   structural sync (settings, schedules, pay items, employees, tax setup,
   compensations) keeps running so subsequent QBO edits remain auditable, but
   Odoo never imports new paychecks again.

The chatter on the config records the cutover with a permanent note.

## 6. Optional archive journal mirror

Tick **Post Archive Journal Per QBO Paycheck** on the same Settings panel
*before* importing historical checks if you want each `qb.payroll.check` to
produce a balanced `account.move` (debit salary expense, credit payroll
liabilities, credit net-pay clearing). The connector skips moves it cannot
balance and logs the reason.

## 7. Post-cutover behaviour

- New payroll runs are created via Odoo's standard `hr.payslip` flow (`Payroll
  > Payslips > New`).
- The KS_SIT rule attached in step 5 consumes the Kansas K-4 fields imported
  from QBO and computes Kansas state income tax during payslip computation.
- Historical paychecks remain visible at `Payroll > Configuration > Salary
  Rules / Structures` (for the imported structures), and at the dedicated
  `qb.payroll.check` model (developer mode: `Settings > Technical > Models`).
- The `quickbooks.sync.log` continues to record sync events; sync errors raise
  the standard mail activity on the affected record.

## 8. Rolling back

To re-enable QBO-side check imports (e.g., during an aborted cutover):

1. Clear `qb_payroll_archived` and `qb_payroll_cutover_date` on the
   `quickbooks.config` row (developer mode or a quick `env['quickbooks.config']`
   write).
2. Re-run the daily cron (`QuickBooks: Pull Payroll (Full)`).

Important: the archive table (`qb.payroll.check`) is the system of record for
historical QBO checks. Do not delete its rows manually - the migration
wizard's idempotency keys assume they remain present once imported.
