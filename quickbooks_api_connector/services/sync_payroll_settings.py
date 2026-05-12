import logging

from odoo import models

_logger = logging.getLogger(__name__)


class QBSyncPayrollSettings(models.AbstractModel):
    _name = 'qb.sync.payroll.settings'
    _description = 'QuickBooks Payroll Settings Snapshot Sync'

    def pull(self, client, config, job):
        return self.pull_all(client, config, 'payroll_settings')

    def push(self, client, config, job):
        _logger.info('Payroll settings are read-only for this connector.')
        return {}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return {'count': 0}
        payroll_client = self.env['qb.payroll.client']
        self.env['ir.config_parameter'].sudo().set_param(
            'quickbooks.payroll.settings.%s' % config.company_id.id,
            str({
                'pay_items': payroll_client.fetch_pay_items(config),
                'pay_schedules': payroll_client.fetch_pay_schedules(config),
                'work_locations': self._work_locations(config),
            }),
        )
        return {'count': 1}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll settings push_all; settings are read-only.')
        return {}

    def _work_locations(self, config):
        try:
            client = self.env['qb.api.client'].get_client(config)
            return {'EmployeeWorkLocation': client.query_all('EmployeeWorkLocation')}
        except Exception as exc:
            return {'error': str(exc)}
