import logging

from . import models

_logger = logging.getLogger(__name__)


def _post_init_seed_payroll(env):
    """Seed payroll structures from QBO for every connected, payroll-enabled company.

    Runs once after the bridge installs. Each step is wrapped so a single
    company's failure does not block the rest of the install.
    """
    if 'quickbooks.config' not in env:
        return
    configs = env['quickbooks.config'].sudo().search([
        ('state', '=', 'connected'),
        ('payroll_enabled', '=', True),
    ])
    if not configs:
        return

    services = [
        'qb.sync.payroll.settings',
        'qb.sync.work.locations',
        'qb.sync.payroll.schedules',
        'qb.sync.payroll.pay.items',
        'qb.sync.payroll.employees',
        'qb.sync.payroll',
        'qb.sync.payroll.checks',
        'qb.sync.payroll.payslips',
        'qb.sync.employee.benefits',
    ]
    for config in configs:
        for service_name in services:
            if service_name not in env:
                continue
            service = env[service_name]
            try:
                service.pull_all(None, config, service_name.split('.')[-1])
            except Exception:
                _logger.exception(
                    'Payroll seed failed for %s on company %s',
                    service_name, config.company_id.name,
                )
