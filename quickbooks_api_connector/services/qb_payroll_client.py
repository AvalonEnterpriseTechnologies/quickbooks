import json
import logging

try:
    import requests as http_requests
except ImportError:
    http_requests = None

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QBO_GRAPHQL_PRODUCTION = 'https://qb.api.intuit.com/graphql'
QBO_GRAPHQL_SANDBOX = 'https://qb-sandbox.api.intuit.com/graphql'

PAYROLL_COMPENSATIONS_QUERY = """
query PayrollEmployeeCompensations {
    payrollEmployeeCompensations {
        employeeId
        compensations {
            id
            name
            type
            active
        }
    }
}
"""


class QBPayrollClient(models.AbstractModel):
    _name = 'qb.payroll.client'
    _description = 'QuickBooks Payroll GraphQL Client'

    def get_graphql_url(self, config):
        if config.environment == 'sandbox':
            return QBO_GRAPHQL_SANDBOX
        return QBO_GRAPHQL_PRODUCTION

    def _execute_graphql(self, config, query, variables=None):
        if http_requests is None:
            raise UserError('The "requests" library is required.')

        auth_service = self.env['qb.auth.service']
        access_token = auth_service.ensure_token_valid(config)
        url = self.get_graphql_url(config)

        headers = {
            'Authorization': 'Bearer %s' % access_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        payload = {'query': query}
        if variables:
            payload['variables'] = variables

        resp = http_requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            _logger.error('Payroll GraphQL error %s: %s', resp.status_code, resp.text[:500])
            raise UserError('Payroll API error: %s' % resp.text[:200])

        data = resp.json()
        if 'errors' in data:
            _logger.error('GraphQL errors: %s', data['errors'])
            raise UserError('Payroll GraphQL error: %s' % data['errors'][0].get('message', ''))
        return data.get('data', {})

    def fetch_compensations(self, config):
        return self._execute_graphql(config, PAYROLL_COMPENSATIONS_QUERY)
