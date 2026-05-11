import logging
import time

from odoo import fields, models

_logger = logging.getLogger(__name__)


PROBE_DEFINITIONS = {
    'recurring_transactions': {
        'type': 'query',
        'entity': 'RecurringTransaction',
    },
    'bundles': {
        'type': 'query',
        'entity': 'Item',
        'where': "Type = 'Group'",
    },
    'projects': {
        'type': 'query',
        'entity': 'Customer',
        'where': "Job = true",
    },
    'time_activities': {
        'type': 'query',
        'entity': 'TimeActivity',
    },
    'expenses': {
        'type': 'query',
        'entity': 'Purchase',
    },
    'payroll_paychecks': {
        'type': 'payroll',
    },
    'inventory_items': {
        'type': 'query',
        'entity': 'Item',
        'where': "Type = 'Inventory'",
    },
    'purchase_orders': {
        'type': 'query',
        'entity': 'PurchaseOrder',
    },
    'estimates': {
        'type': 'query',
        'entity': 'Estimate',
    },
    'sales_receipts': {
        'type': 'query',
        'entity': 'SalesReceipt',
    },
    'custom_field_definitions': {
        'type': 'unsupported',
    },
    'attachments': {
        'type': 'query',
        'entity': 'Attachable',
    },
    'classes': {
        'type': 'query',
        'entity': 'Class',
    },
    'departments': {
        'type': 'query',
        'entity': 'Department',
    },
}


class QBDataProbe(models.AbstractModel):
    _name = 'qb.data.probe'
    _description = 'QuickBooks Data Presence Probe Service'

    def run_all(self, config):
        client = self.env['qb.api.client'].get_client(config)
        results = {}
        for area in PROBE_DEFINITIONS:
            results[area] = self.run_area(config, client, area)
        return results

    def run_area(self, config, client, area):
        definition = PROBE_DEFINITIONS[area]
        started = time.time()
        count = 0
        error_message = False
        try:
            if definition['type'] == 'query':
                count = self._probe_query(client, definition)
            elif definition['type'] == 'payroll':
                count = self._probe_payroll_checks(config)
            else:
                count = 0
        except Exception as exc:
            _logger.info('QBO data probe failed for %s: %s', area, exc)
            error_message = str(exc)

        duration_ms = int((time.time() - started) * 1000)
        vals = {
            'company_id': config.company_id.id,
            'area': area,
            'has_data': count > 0,
            'sample_count': count,
            'last_probed_at': fields.Datetime.now(),
            'probe_duration_ms': duration_ms,
            'error_message': error_message,
        }
        probe = self.env['quickbooks.data.probe'].sudo().search([
            ('company_id', '=', config.company_id.id),
            ('area', '=', area),
        ], limit=1)
        if probe:
            probe.write(vals)
        else:
            probe = self.env['quickbooks.data.probe'].sudo().create(vals)
        return probe

    def _probe_query(self, client, definition):
        query = 'SELECT COUNT(*) FROM %s' % definition['entity']
        if definition.get('where'):
            query += ' WHERE %s' % definition['where']
        response = client.query(query)
        query_response = response.get('QueryResponse', {})
        total_count = query_response.get('totalCount')
        if total_count is not None:
            return int(total_count)
        records = query_response.get(definition['entity'], [])
        return len(records)

    def _probe_payroll_checks(self, config):
        if not getattr(config, 'payroll_enabled', False):
            return 0
        client = self.env['qb.payroll.client']
        data = client.fetch_checks(config)
        return len(data.get('payrollChecks') or [])
