import logging

from odoo import fields, models

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

        pay_items = self._safe(lambda: payroll_client.fetch_pay_items(config))
        pay_schedules = self._safe(lambda: payroll_client.fetch_pay_schedules(config))
        work_locations = self._work_locations(config)

        if 'qb.payroll.settings.snapshot' in self.env:
            Snapshot = self.env['qb.payroll.settings.snapshot'].sudo()
            Snapshot.create({
                'company_id': config.company_id.id,
                'captured_at': fields.Datetime.now(),
                'pay_items_json': pay_items,
                'pay_schedules_json': pay_schedules,
                'work_locations_json': work_locations,
                'raw_json': {
                    'pay_items': pay_items,
                    'pay_schedules': pay_schedules,
                    'work_locations': work_locations,
                },
            })
        else:
            # Bridge not loaded; fall back to ir.config_parameter so the data
            # is at least retained for support investigations.
            self.env['ir.config_parameter'].sudo().set_param(
                'quickbooks.payroll.settings.%s' % config.company_id.id,
                str({
                    'pay_items': pay_items,
                    'pay_schedules': pay_schedules,
                    'work_locations': work_locations,
                }),
            )
        return {'count': 1}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll settings push_all; settings are read-only.')
        return {}

    @staticmethod
    def _safe(callable_):
        try:
            return callable_() or {}
        except Exception as exc:
            _logger.info('Payroll settings fetch failed: %s', exc)
            return {'error': str(exc)}

    def _work_locations(self, config):
        try:
            client = self.env['qb.api.client'].get_client(config)
            return {'EmployeeWorkLocation': client.query_all('EmployeeWorkLocation')}
        except Exception as exc:
            return {'error': str(exc)}
