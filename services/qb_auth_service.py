import hashlib
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QBO_AUTH_BASE = 'https://appcenter.intuit.com/connect/oauth2'
QBO_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
QBO_SANDBOX_BASE = 'https://sandbox-quickbooks.api.intuit.com'
QBO_PRODUCTION_BASE = 'https://quickbooks.api.intuit.com'

SCOPES = 'com.intuit.quickbooks.accounting'


class QBAuthService(models.AbstractModel):
    _name = 'qb.auth.service'
    _description = 'QuickBooks OAuth 2.0 Service'

    def _get_redirect_uri(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/qb/oauth/callback' % base_url.rstrip('/')

    def get_authorization_url(self, config):
        state = secrets.token_urlsafe(32)
        config.sudo().write({'error_message': state})

        params = {
            'client_id': config.client_id,
            'scope': SCOPES,
            'redirect_uri': self._get_redirect_uri(),
            'response_type': 'code',
            'state': state,
        }
        query = '&'.join('%s=%s' % (k, v) for k, v in params.items())
        return '%s?%s' % (QBO_AUTH_BASE, query)

    def exchange_code_for_tokens(self, config, code):
        import requests

        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self._get_redirect_uri(),
        }
        auth = (config.client_id, config.client_secret)
        resp = requests.post(QBO_TOKEN_URL, data=data, auth=auth, timeout=30)
        if resp.status_code != 200:
            _logger.error('Token exchange failed: %s %s', resp.status_code, resp.text)
            raise UserError(
                'Failed to exchange authorization code: %s' % resp.text
            )
        token_data = resp.json()
        config.set_tokens(
            access_token=token_data['access_token'],
            refresh_token=token_data['refresh_token'],
            expires_in=token_data.get('expires_in', 3600),
        )
        return token_data

    def refresh_token(self, config):
        import requests

        refresh = config.get_refresh_token()
        if not refresh:
            raise UserError('No refresh token available. Please reconnect.')

        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh,
        }
        auth = (config.client_id, config.client_secret)
        resp = requests.post(QBO_TOKEN_URL, data=data, auth=auth, timeout=30)
        if resp.status_code != 200:
            _logger.error('Token refresh failed: %s %s', resp.status_code, resp.text)
            config.write({
                'state': 'error',
                'error_message': 'Token refresh failed: %s' % resp.text,
            })
            raise UserError('Token refresh failed: %s' % resp.text)

        token_data = resp.json()
        config.set_tokens(
            access_token=token_data['access_token'],
            refresh_token=token_data['refresh_token'],
            expires_in=token_data.get('expires_in', 3600),
        )
        _logger.info('Token refreshed for company %s', config.company_id.name)
        return token_data

    def ensure_token_valid(self, config):
        if config.is_token_expired():
            self.refresh_token(config)
        return config.get_access_token()

    def get_api_base_url(self, config):
        if config.environment == 'sandbox':
            return QBO_SANDBOX_BASE
        return QBO_PRODUCTION_BASE
