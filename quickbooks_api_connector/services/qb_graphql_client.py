import logging
import time

try:
    import requests as http_requests
except ImportError:
    http_requests = None

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QBO_GRAPHQL_PRODUCTION = 'https://qb.api.intuit.com/graphql'
QBO_GRAPHQL_SANDBOX = 'https://qb-sandbox.api.intuit.com/graphql'
MAX_RETRIES_5XX = 3


class QBGraphQLClient(models.AbstractModel):
    _name = 'qb.graphql.client'
    _description = 'QuickBooks GraphQL Client'

    def get_graphql_url(self, config):
        if config.environment == 'sandbox':
            return QBO_GRAPHQL_SANDBOX
        return QBO_GRAPHQL_PRODUCTION

    def execute_graphql(self, config, query, variables=None, retries=0):
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
        if resp.status_code in (500, 502, 503, 504):
            if retries >= MAX_RETRIES_5XX:
                raise UserError('QuickBooks GraphQL error: %s' % resp.text[:200])
            wait = min(2 ** retries * 5, 60)
            _logger.warning('QuickBooks GraphQL %s - backing off %ds', resp.status_code, wait)
            time.sleep(wait)
            return self.execute_graphql(
                config, query, variables=variables, retries=retries + 1,
            )
        if resp.status_code != 200:
            _logger.error('QuickBooks GraphQL error %s: %s', resp.status_code, resp.text[:500])
            raise UserError('QuickBooks GraphQL error: %s' % resp.text[:200])

        data = resp.json()
        if 'errors' in data:
            _logger.error('GraphQL errors: %s', data['errors'])
            raise UserError(
                'QuickBooks GraphQL error: %s'
                % data['errors'][0].get('message', '')
            )
        return data.get('data', {})
