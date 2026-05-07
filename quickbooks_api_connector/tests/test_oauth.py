from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

from .common import QuickbooksTestCommon


class TestOAuth(QuickbooksTestCommon):

    def test_authorization_url_generation(self):
        """Test that the auth URL contains required OAuth parameters."""
        auth_service = self.env['qb.auth.service']
        url = auth_service.get_authorization_url(self.config)
        self.assertIn('client_id=test_client_id', url)
        self.assertIn('response_type=code', url)
        self.assertIn('scope=com.intuit.quickbooks.accounting', url)
        self.assertIn('redirect_uri=', url)
        self.assertIn('state=', url)
        self.assertTrue(self.config.oauth_state)

    def test_authorization_url_encodes_multi_scope(self):
        """Payroll-enabled auth URLs must percent-encode space-delimited scopes."""
        self.config.payroll_enabled = True
        auth_service = self.env['qb.auth.service']
        url = auth_service.get_authorization_url(self.config)
        self.assertIn('com.intuit.quickbooks.accounting+payroll.compensation.read', url)

    @patch('requests.post')
    def test_exchange_code_success(self, mock_post):
        """Test successful token exchange."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                'access_token': 'new_access_token',
                'refresh_token': 'new_refresh_token',
                'expires_in': 3600,
            }),
        )
        auth_service = self.env['qb.auth.service']
        result = auth_service.exchange_code_for_tokens(self.config, 'test_auth_code')

        self.assertEqual(result['access_token'], 'new_access_token')
        self.assertEqual(self.config.state, 'connected')

    @patch('requests.post')
    def test_exchange_code_failure(self, mock_post):
        """Test token exchange failure raises UserError."""
        mock_post.return_value = MagicMock(
            status_code=400,
            text='invalid_grant',
        )
        auth_service = self.env['qb.auth.service']
        with self.assertRaises(UserError):
            auth_service.exchange_code_for_tokens(self.config, 'bad_code')

    @patch('requests.post')
    def test_refresh_token_success(self, mock_post):
        """Test token refresh flow."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                'access_token': 'refreshed_access',
                'refresh_token': 'refreshed_refresh',
                'expires_in': 3600,
            }),
        )
        auth_service = self.env['qb.auth.service']
        result = auth_service.refresh_token(self.config)
        self.assertEqual(result['access_token'], 'refreshed_access')
        self.assertEqual(self.config.state, 'connected')

    @patch('requests.post')
    def test_refresh_token_failure_marks_error(self, mock_post):
        """Test that refresh failure marks config as error."""
        mock_post.return_value = MagicMock(
            status_code=400,
            text='invalid_grant',
        )
        auth_service = self.env['qb.auth.service']
        with self.assertRaises(UserError):
            auth_service.refresh_token(self.config)
        self.assertEqual(self.config.state, 'error')

    def test_token_encryption_roundtrip(self):
        """Test that tokens survive encrypt/decrypt cycle."""
        test_secret = 'super_secret_value_12345'
        encrypted = self.config._encrypt(test_secret)
        self.assertNotEqual(encrypted, test_secret)
        decrypted = self.config._decrypt(encrypted)
        self.assertEqual(decrypted, test_secret)

    def test_token_expired_check(self):
        """Test token expiry detection."""
        from datetime import timedelta
        from odoo import fields

        self.config.token_expiry = fields.Datetime.now() + timedelta(hours=1)
        self.assertFalse(self.config.is_token_expired())

        self.config.token_expiry = fields.Datetime.now() - timedelta(minutes=1)
        self.assertTrue(self.config.is_token_expired())

    def test_api_base_url_sandbox(self):
        """Test sandbox URL selection."""
        auth_service = self.env['qb.auth.service']
        self.config.environment = 'sandbox'
        url = auth_service.get_api_base_url(self.config)
        self.assertIn('sandbox', url)

    def test_api_base_url_production(self):
        """Test production URL selection."""
        auth_service = self.env['qb.auth.service']
        self.config.environment = 'production'
        url = auth_service.get_api_base_url(self.config)
        self.assertNotIn('sandbox', url)
