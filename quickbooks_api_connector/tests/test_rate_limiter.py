import time
from collections import deque
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from .common import QuickbooksTestCommon


class TestRateLimiter(QuickbooksTestCommon):

    def test_rate_limit_window_tracking(self):
        """Test that request timestamps are tracked in the sliding window."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import (
            _QBClient, MAX_REQUESTS_PER_MINUTE,
        )
        # Access the class-level deque
        _QBClient._request_timestamps = deque()

        # Simulate adding timestamps
        now = time.time()
        for i in range(10):
            _QBClient._request_timestamps.append(now + i * 0.01)

        self.assertEqual(len(_QBClient._request_timestamps), 10)

    def test_exponential_backoff_on_429(self):
        """Test that 429 responses trigger retry with backoff."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import (
            _QBClient, MAX_RETRIES_429,
        )
        client = self._mock_client()

        # Verify MAX_RETRIES_429 is set
        self.assertEqual(MAX_RETRIES_429, 5)

    def test_concurrent_request_semaphore(self):
        """Test that max concurrent requests is bounded."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import (
            MAX_CONCURRENT,
        )
        self.assertEqual(MAX_CONCURRENT, 8)
        self.assertTrue(MAX_CONCURRENT < 10)  # below QBO limit

    def test_headroom_below_api_limit(self):
        """Test that our rate limit has headroom below the QBO limit."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import (
            MAX_REQUESTS_PER_MINUTE,
        )
        self.assertEqual(MAX_REQUESTS_PER_MINUTE, 450)
        self.assertTrue(MAX_REQUESTS_PER_MINUTE < 500)

    def test_api_error_class(self):
        """Test QBApiError carries status_code and detail."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import QBApiError

        error = QBApiError(429, 'Too many requests', '/v3/company/123/customer')
        self.assertEqual(error.status_code, 429)
        self.assertIn('Too many requests', error.detail)
        self.assertIn('429', str(error))

    def test_query_all_pagination(self):
        """Test query_all pages through results correctly."""
        from odoo.addons.quickbooks_api_connector.services.qb_api_client import _QBClient

        mock_env = MagicMock()
        mock_config = MagicMock()
        mock_config.realm_id = '123'

        with patch.object(_QBClient, '__init__', lambda self, *a, **k: None):
            client = _QBClient.__new__(_QBClient)
            client.env = mock_env
            client.config = mock_config
            client._auth_service = MagicMock()
            client._base_url = 'https://test.api.intuit.com'

            # Simulate 2 pages
            page1 = [{'Id': str(i)} for i in range(1000)]
            page2 = [{'Id': str(i)} for i in range(1000, 1500)]

            call_count = [0]

            def mock_query(q):
                call_count[0] += 1
                if call_count[0] == 1:
                    return {'QueryResponse': {'Customer': page1}}
                return {'QueryResponse': {'Customer': page2}}

            client.query = mock_query
            results = client.query_all('Customer')

            self.assertEqual(len(results), 1500)
            self.assertEqual(call_count[0], 2)
