import json
import logging

from odoo import http
from odoo.http import request

from ..services.qb_api_client import QBApiError

_logger = logging.getLogger(__name__)

QBO_APP_AUTH_FAILED_CODE = '3100'
QBO_APP_AUTH_FAILED_HINT = (
    "QuickBooks accepted the OAuth grant but reported "
    "ApplicationAuthorizationFailed (error 3100) on the very first API call. "
    "This is an Intuit-side configuration mismatch, not a token problem. "
    "Confirm: (1) the Client ID and Client Secret in this Odoo configuration "
    "are taken from the *same* environment (Development = Sandbox, Production "
    "= live) as the QuickBooks company you just authorized; (2) the Intuit "
    "Developer Portal app's Redirect URIs list contains the exact OAuth "
    "Redirect URI shown on the QuickBooks settings page; (3) the app has not "
    "been disconnected on the Intuit side. Tokens have been saved, so you can "
    "fix the keys/environment and click 'Test QuickBooks Company Connection' "
    "without re-running the OAuth flow."
)


class QuickbooksOAuthController(http.Controller):

    @http.route('/qb/oauth/callback', type='http', auth='public', csrf=False)
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code')
        state = kwargs.get('state')
        realm_id = kwargs.get('realmId')
        error = kwargs.get('error')
        config = request.env['quickbooks.config'].sudo().search([
            ('oauth_state', '=', state),
        ], limit=1) if state else request.env['quickbooks.config'].sudo().browse()

        if error:
            _logger.error('OAuth error: %s', error)
            if config:
                config.write({
                    'state': 'error',
                    'oauth_state': False,
                    'error_message': 'Authorization denied: %s' % error,
                })
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {'success': False, 'message': 'Authorization denied: %s' % error},
            )

        if not code or not realm_id:
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {'success': False, 'message': 'Missing authorization code or realm ID.'},
            )

        if not config:
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {'success': False, 'message': 'Security validation failed (state mismatch).'},
            )

        if config.oauth_state != state:
            _logger.warning('CSRF state mismatch in QB OAuth callback')
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {'success': False, 'message': 'Security validation failed (state mismatch).'},
            )

        # Step 1: exchange the authorization code for tokens. A failure here
        # means the OAuth grant itself is broken (bad code, bad client secret,
        # redirect URI mismatch). It is the only step that should fail the
        # whole flow.
        try:
            auth_service = request.env['qb.auth.service']
            auth_service.exchange_code_for_tokens(config, code)
        except Exception as exc:
            _logger.exception('QuickBooks token exchange failed')
            config.write({
                'state': 'error',
                'oauth_state': False,
                'error_message': str(exc),
            })
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {
                    'success': False,
                    'message': 'Token exchange failed: %s' % str(exc),
                },
            )

        config.write({
            'realm_id': realm_id,
            'oauth_state': False,
            'error_message': False,
        })

        # Step 2: try to read the QBO company display name. This is a *post*
        # connection check; if it fails the OAuth handshake is still valid and
        # the tokens are still good, so we keep the config in 'connected'
        # state and surface a remediation hint instead of throwing the user
        # back to square one.
        api_client = request.env['qb.api.client']
        client = api_client.get_client(config)
        try:
            info = client.get('companyinfo/%s' % realm_id)
            company_name = info.get('CompanyInfo', {}).get('CompanyName', '')
            config.write({'qb_company_name': company_name})
            return request.render(
                'quickbooks_api_connector.qb_oauth_result_template',
                {
                    'success': True,
                    'message': 'Successfully connected to %s!' % company_name,
                },
            )
        except Exception as exc:
            return self._render_post_connect_failure(config, exc)

    def _render_post_connect_failure(self, config, exc):
        """Tokens were saved; only the post-connect read-back failed."""
        _logger.exception('QuickBooks post-connect read-back failed')
        message, hint = self._post_connect_message(exc)
        config.write({'error_message': message})
        return request.render(
            'quickbooks_api_connector.qb_oauth_result_template',
            {
                'success': False,
                'message': '%s %s' % (message, hint),
            },
        )

    @staticmethod
    def _post_connect_message(exc):
        """Build a human-readable message + hint for a post-connect failure.

        Recognises QBO ApplicationAuthorizationFailed (3100) which is by far
        the most common reason the first API call fails after a successful
        token exchange (sandbox/production key mismatch, app disconnected on
        Intuit's side, etc.). Falls back to the raw exception string for
        anything else.
        """
        detail = getattr(exc, 'detail', '') or str(exc)
        codes = set()
        if isinstance(exc, QBApiError):
            try:
                payload = json.loads(detail) if isinstance(detail, str) else {}
            except ValueError:
                payload = {}
            errors = (
                (payload.get('fault') or payload.get('Fault') or {}).get('error')
                or (payload.get('fault') or payload.get('Fault') or {}).get('Error')
                or []
            )
            for err in errors:
                code = str(err.get('code') or err.get('Code') or '').lstrip('0')
                if code:
                    codes.add(code)
        if QBO_APP_AUTH_FAILED_CODE in codes:
            return (
                'Tokens saved, but QuickBooks rejected the very first API '
                'call with ApplicationAuthorizationFailed (3100).',
                QBO_APP_AUTH_FAILED_HINT,
            )
        return (
            'Tokens saved, but the post-connect read-back failed: %s' % str(exc),
            'You can keep the saved tokens and retry the read-back from '
            'Settings > QuickBooks > Test QuickBooks Company Connection '
            'after correcting the underlying issue.',
        )
