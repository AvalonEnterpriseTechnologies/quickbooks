import logging

from odoo import models

_logger = logging.getLogger(__name__)


# Ordered for dependency safety. Settings + work locations + schedules + items
# all populate the structures that the per-employee / per-check rows then link to.
ORCHESTRATED_ORDER = [
    ('qb.sync.payroll.settings', 'payroll_settings'),
    ('qb.sync.work.locations', 'work_location'),
    ('qb.sync.payroll.schedules', 'payroll_schedule'),
    ('qb.sync.payroll.pay.items', 'payroll_pay_item'),
    ('qb.sync.payroll.employees', 'payroll_employee'),
    ('qb.sync.payroll.employees', 'payroll_tax_setup'),
    ('qb.sync.payroll', 'payroll_compensation'),
    ('qb.sync.payroll.checks', 'payroll_check'),
    ('qb.sync.employee.benefits', 'employee_benefit'),
]


class QBSyncPayrollOrchestrator(models.AbstractModel):
    _name = 'qb.sync.payroll.orchestrator'
    _description = 'QuickBooks Payroll Orchestrator'

    def cron_pull_for_all_companies(self):
        Config = self.env['quickbooks.config']
        configs = Config.search([
            ('state', '=', 'connected'),
            ('payroll_enabled', '=', True),
        ])
        for config in configs:
            try:
                self.pull_for_config(config)
            except Exception:
                _logger.exception(
                    'Payroll orchestrator pull failed for company %s',
                    config.company_id.name,
                )

    def pull_for_config(self, config):
        """Walk every payroll sync service in dependency order.

        After cutover (`qb_payroll_archived = True`), check / benefit pulls
        are skipped so QBO's continued payroll runs do not pollute the
        Odoo-of-record archive.
        """
        archived = bool(getattr(config, 'qb_payroll_archived', False))
        for service_name, entity_type in ORCHESTRATED_ORDER:
            if archived and entity_type in ('payroll_check', 'employee_benefit'):
                continue
            if not self._toggle_enabled(config, entity_type):
                continue
            if service_name not in self.env:
                continue
            service = self.env[service_name]
            try:
                service.pull_all(None, config, entity_type)
            except Exception:
                _logger.exception(
                    'Payroll orchestrator: %s failed for company %s',
                    service_name, config.company_id.name,
                )

    @staticmethod
    def _toggle_enabled(config, entity_type):
        toggle_map = {
            'payroll_settings': 'sync_payroll_settings',
            'work_location': 'payroll_enabled',
            'payroll_schedule': 'sync_payroll_pay_schedules',
            'payroll_pay_item': 'sync_payroll_pay_items',
            'payroll_employee': 'sync_payroll_employees',
            'payroll_tax_setup': 'sync_payroll_tax_setup',
            'payroll_compensation': 'sync_payroll_compensations',
            'payroll_check': 'sync_payroll_checks',
            'employee_benefit': 'sync_employee_benefits',
        }
        attribute = toggle_map.get(entity_type)
        if not attribute:
            return True
        return bool(getattr(config, attribute, False) or getattr(config, 'payroll_enabled', False))
