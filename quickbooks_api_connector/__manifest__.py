{
    'name': 'QuickBooks API Connector',
    'version': '19.0.8.0.0',
    'category': 'Accounting',
    'summary': 'Full QuickBooks Online connector for Odoo 19 — Accounting, Payroll, Time',
    'description': """
        Comprehensive QuickBooks Online integration for Odoo 19.

        UI policy
        ---------
        This module ships exactly ONE custom UI view: the QuickBooks block
        on the standard ``Settings`` panel (an inherit of
        ``base_setup.res_config_settings_view_form``). Every other piece of
        QuickBooks information is surfaced through native Odoo features:

          * Per-record sync history -> the standard chatter on the affected
            record (``res.partner``, ``account.move``, ``account.account``,
            ``product.product``, ``account.analytic.line``). The connector
            sets ``tracking=True`` on the meaningful ``qb_*`` fields and
            posts to the chatter via ``quickbooks.sync.log.log_sync``.
          * Permanent sync failures -> a native ``mail.activity`` (warning
            To-do) on the underlying record, assigned to the QuickBooks
            Manager group.
          * Per-record actions ("Sync to QuickBooks", "View QBO Balances",
            "View QBO Sub-accounts", "Post Opening Balances") -> Odoo's
            standard ``Action`` dropdown via ``ir.actions.server`` records
            with ``binding_model_id`` set to the native model.
          * Live counters (queue depth, failed jobs, errors / successes in
            the last 24 hours, last successful sync) and the coverage
            matrix -> read-only fields rendered inline on the Settings
            panel.

        New ``ir.ui.view`` records or ``ir.ui.menu`` records added in this
        module are not allowed; surface the information through native
        Odoo views instead.

        Requirements:
        - The Odoo Accounting module (`account`) is a hard prerequisite
          and is installed automatically with this module. The Enterprise
          Accountant app (`account_accountant`) is also a hard
          prerequisite — Odoo's dependency resolver installs it before
          this module loads, guaranteeing the full Accounting UI is
          available on every deploy. The connector therefore requires
          an Odoo Enterprise environment (or a community deploy whose
          addons path includes `account_accountant`); it will refuse to
          install otherwise.

        Features:
        - One-time OAuth 2.0 setup, sync controls, and live status all in
          ``Settings > QuickBooks``.
        - Bidirectional sync: customers, vendors, products, invoices,
          bills, payments, journal entries, tax codes, vendor credits,
          refund receipts, deposits, transfers, classes, payment terms.
        - Extended sync (suggests optional Odoo modules only when needed):
          purchase orders (purchase), expenses (hr_expense),
          employees/departments (hr), projects (project), timesheets
          (hr_timesheet), inventory quantities (stock), sales (sale).
        - QuickBooks Payroll API (GraphQL) integration.
        - QuickBooks Time API (TSheets) integration.
        - Async queue-based processing with retry and backoff.
        - CDC (Change Data Capture) for efficient incremental sync.
        - Conflict resolution (last modified, Odoo wins, QBO wins, manual).
        - Configurable field mappings.
        - Webhook support (CloudEvents + legacy format).
        - Rate-limited API client (sliding window, 450 req/min).

        Optional modules are never installed automatically. The connector
        probes QBO for associated data and suggests installation only when
        data exists and the user explicitly confirms.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': [
        'base', 'base_setup', 'mail', 'account',
        'account_accountant',
        'contacts',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        # Security groups (must come before access CSV)
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        # Data
        'data/cron_jobs.xml',
        'data/mail_templates.xml',
        'data/default_field_mappings.xml',
        # Action bindings expose connector actions on native models'
        # standard "Action" dropdown without inheriting their views.
        'data/server_actions.xml',
        # The single allowed UI view: Settings > QuickBooks block.
        'views/res_config_settings_views.xml',
        # The opening-balances posting wizard. Triggered from the
        # account.journal Action menu via server_actions.xml; this is the
        # only transient-model form view in the module because it requires
        # several user inputs (snapshot, journal, equity / retained
        # earnings accounts) that cannot be inlined into Settings.
        'wizards/qb_post_opening_balances_wizard_views.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
}
