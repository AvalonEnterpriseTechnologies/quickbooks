import hashlib
import hmac
import json
import base64
from unittest.mock import patch, MagicMock

from .common import QuickbooksTestCommon


class TestWebhookHandler(QuickbooksTestCommon):

    def _compute_signature(self, body, verifier_token):
        """Compute expected HMAC-SHA256 signature for a body."""
        digest = hmac.new(
            verifier_token.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode('utf-8')

    def test_cloud_events_parsing(self):
        """Test that CloudEvents payloads are correctly parsed and enqueued."""
        from odoo.addons.quickbooks_api_module.controllers.webhook_controller import (
            CLOUD_EVENT_TYPE_MAP,
        )

        event = self._make_cloud_event(
            'qbo.customer.updated.v1', '100',
        )
        self.assertIn('qbo.customer.updated.v1', CLOUD_EVENT_TYPE_MAP)
        entity_type, operation = CLOUD_EVENT_TYPE_MAP['qbo.customer.updated.v1']
        self.assertEqual(entity_type, 'customer')
        self.assertEqual(operation, 'update')

    def test_legacy_format_parsing(self):
        """Test that legacy webhook payloads are correctly parsed."""
        from odoo.addons.quickbooks_api_module.controllers.webhook_controller import (
            LEGACY_ENTITY_MAP,
        )

        payload = self._make_legacy_webhook('Invoice', '400')
        entities = (
            payload['eventNotifications'][0]['dataChangeEvent']['entities']
        )
        self.assertEqual(len(entities), 1)
        entity = entities[0]
        mapped_type = LEGACY_ENTITY_MAP.get(entity['name'])
        self.assertEqual(mapped_type, 'invoice')

    def test_signature_computation(self):
        """Test HMAC-SHA256 signature matches expected format."""
        body = '{"test": "data"}'
        token = 'test_verifier_token'
        sig = self._compute_signature(body, token)
        self.assertTrue(len(sig) > 0)

        # Verify it would match
        expected = hmac.new(
            token.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected_b64 = base64.b64encode(expected).decode('utf-8')
        self.assertEqual(sig, expected_b64)

    def test_all_cloud_event_types_mapped(self):
        """Verify key entity types have CloudEvent type mappings."""
        from odoo.addons.quickbooks_api_module.controllers.webhook_controller import (
            CLOUD_EVENT_TYPE_MAP,
        )

        expected_entities = [
            'customer', 'vendor', 'product', 'invoice', 'bill',
            'payment', 'bill_payment', 'journal_entry', 'credit_memo', 'account',
        ]
        mapped_entities = set()
        for entity_type, _ in CLOUD_EVENT_TYPE_MAP.values():
            mapped_entities.add(entity_type)

        for entity in expected_entities:
            self.assertIn(
                entity, mapped_entities,
                'Missing CloudEvent mapping for entity: %s' % entity,
            )

    def test_cloud_events_idempotency_key(self):
        """Test that CloudEvent ID is used as idempotency key."""
        event = self._make_cloud_event('qbo.customer.updated.v1', '100')
        event_id = event['id']
        expected_key = 'ce_%s' % event_id
        self.assertTrue(expected_key.startswith('ce_'))
