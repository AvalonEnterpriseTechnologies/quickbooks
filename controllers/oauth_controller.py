import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class QuickbooksOAuthController(http.Controller):

    @http.route('/qb/oauth/callback', type='http', auth='user', csrf=False)
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code')
        state = kwargs.get('state')
        realm_id = kwargs.get('realmId')
        error = kwargs.get('error')

        if error:
            _logger.error('OAuth error: %s', error)
            return request.render(
                'quickbooks.qb_oauth_result_template',
                {'success': False, 'message': 'Authorization denied: %s' % error},
            )

        if not code or not realm_id:
            return request.render(
                'quickbooks.qb_oauth_result_template',
                {'success': False, 'message': 'Missing authorization code or realm ID.'},
            )

        config = request.env['quickbooks.config'].sudo().search([
            ('company_id', '=', request.env.company.id),
        ], limit=1)

        if not config:
            return request.render(
                'quickbooks.qb_oauth_result_template',
                {'success': False, 'message': 'No QuickBooks configuration found.'},
            )

        stored_state = config.error_message
        if stored_state != state:
            _logger.warning('CSRF state mismatch in QB OAuth callback')
            return request.render(
                'quickbooks.qb_oauth_result_template',
                {'success': False, 'message': 'Security validation failed (state mismatch).'},
            )

        try:
            auth_service = request.env['qb.auth.service']
            auth_service.exchange_code_for_tokens(config, code)
            config.write({
                'realm_id': realm_id,
                'error_message': False,
            })

            api_client = request.env['qb.api.client']
            client = api_client.get_client(config)
            info = client.get('companyinfo/%s' % realm_id)
            company_name = info.get('CompanyInfo', {}).get('CompanyName', '')
            config.write({'qb_company_name': company_name})

            return request.render(
                'quickbooks.qb_oauth_result_template',
                {
                    'success': True,
                    'message': 'Successfully connected to %s!' % company_name,
                },
            )
        except Exception as e:
            _logger.exception('OAuth callback processing failed')
            config.write({
                'state': 'error',
                'error_message': str(e),
            })
            return request.render(
                'quickbooks.qb_oauth_result_template',
                {'success': False, 'message': 'Connection failed: %s' % str(e)},
            )
