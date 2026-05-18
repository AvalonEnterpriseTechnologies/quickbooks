{
    'name': 'QuickBooks API Connector — HR Payroll Bridge',
    'version': '19.0.2.0.2',
    'category': 'Accounting',
    'summary': 'QuickBooks Payroll sync fields and archive for Odoo Payroll',
    'description': """
        Bridge module that wires QuickBooks Payroll GraphQL data into Odoo
        Payroll native models (hr.contract, hr.payslip, hr.payslip.input,
        hr.salary.rule, hr.payroll.structure, hr.payroll.structure.type)
        and into a dedicated read-only archive (qb.payroll.check) so
        historical QuickBooks paychecks remain auditable after Odoo
        takes over as the live payroll system of record.

        Enterprise-only. The dependencies ``hr_payroll`` and
        ``hr_contract`` ship with the Odoo Enterprise stack. On
        Community deployments (or Enterprise images where those modules
        are not loaded) they are not present in the addons path, which
        makes Odoo raise

            UserError: You try to install module
            "quickbooks_api_connector_hr_payroll" that depends on
            module "hr_contract". But the latter module is not
            available in your system.

        whenever Odoo tries to auto-install the bridge. To avoid
        breaking those deployments the manifest ships with
        ``installable=False``. The main ``quickbooks_api_connector``
        module's sync services already guard against the bridge being
        absent — they no-op gracefully and log a warning when the
        ``qb_*`` fields are missing.

        To enable the bridge on an Enterprise deployment:

            1. Confirm ``hr_payroll`` and ``hr_contract`` are present
               in the addons path (``odoo-bin --list-addons`` shows
               them).
            2. Edit this manifest and set both ``installable`` and
               ``auto_install`` to ``True``.
            3. Restart Odoo with ``-u quickbooks_api_connector``; the
               bridge auto-installs and the ``post_init_hook`` seeds
               payroll data for every connected, payroll-enabled
               company.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr_payroll', 'hr_contract'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'post_init_hook': '_post_init_seed_payroll',
    # Enterprise-only. See the description above for the one-line flip
    # needed on deployments where ``hr_payroll`` + ``hr_contract`` are
    # actually present in the addons path.
    'installable': False,
    'auto_install': False,
    'application': False,
}
