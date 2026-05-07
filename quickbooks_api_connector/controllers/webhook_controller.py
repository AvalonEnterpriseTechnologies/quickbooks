import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# CloudEvents type → (entity_type, operation)
CLOUD_EVENT_TYPE_MAP = {
    'qbo.customer.created.v1': ('customer', 'create'),
    'qbo.customer.updated.v1': ('customer', 'update'),
    'qbo.customer.deleted.v1': ('customer', 'delete'),
    'qbo.vendor.created.v1': ('vendor', 'create'),
    'qbo.vendor.updated.v1': ('vendor', 'update'),
    'qbo.vendor.deleted.v1': ('vendor', 'delete'),
    'qbo.item.created.v1': ('product', 'create'),
    'qbo.item.updated.v1': ('product', 'update'),
    'qbo.item.deleted.v1': ('product', 'delete'),
    'qbo.invoice.created.v1': ('invoice', 'create'),
    'qbo.invoice.updated.v1': ('invoice', 'update'),
    'qbo.invoice.deleted.v1': ('invoice', 'delete'),
    'qbo.invoice.voided.v1': ('invoice', 'delete'),
    'qbo.bill.created.v1': ('bill', 'create'),
    'qbo.bill.updated.v1': ('bill', 'update'),
    'qbo.bill.deleted.v1': ('bill', 'delete'),
    'qbo.payment.created.v1': ('payment', 'create'),
    'qbo.payment.updated.v1': ('payment', 'update'),
    'qbo.payment.deleted.v1': ('payment', 'delete'),
    'qbo.billpayment.created.v1': ('bill_payment', 'create'),
    'qbo.billpayment.updated.v1': ('bill_payment', 'update'),
    'qbo.billpayment.deleted.v1': ('bill_payment', 'delete'),
    'qbo.journalentry.created.v1': ('journal_entry', 'create'),
    'qbo.journalentry.updated.v1': ('journal_entry', 'update'),
    'qbo.journalentry.deleted.v1': ('journal_entry', 'delete'),
    'qbo.creditmemo.created.v1': ('credit_memo', 'create'),
    'qbo.creditmemo.updated.v1': ('credit_memo', 'update'),
    'qbo.creditmemo.deleted.v1': ('credit_memo', 'delete'),
    'qbo.account.created.v1': ('account', 'create'),
    'qbo.account.updated.v1': ('account', 'update'),
    'qbo.account.deleted.v1': ('account', 'delete'),
    'qbo.project.created.v1': ('project', 'create'),
    'qbo.project.updated.v1': ('project', 'update'),
    'qbo.project.deleted.v1': ('project', 'delete'),
    'qbo.itemadjustment.created.v1': ('inventory_adjustment', 'create'),
    'qbo.itemadjustment.updated.v1': ('inventory_adjustment', 'update'),
    'qbo.itemadjustment.deleted.v1': ('inventory_adjustment', 'delete'),
}

# Fallback for legacy format entity names
LEGACY_ENTITY_MAP = {
    'Customer': 'customer',
    'Vendor': 'vendor',
    'Item': 'product',
    'Invoice': 'invoice',
    'Bill': 'bill',
    'Payment': 'payment',
    'BillPayment': 'bill_payment',
    'JournalEntry': 'journal_entry',
    'CreditMemo': 'credit_memo',
    'Account': 'account',
    'Project': 'project',
    'ItemAdjustment': 'inventory_adjustment',
}


class QuickbooksWebhookController(http.Controller):

    @http.route('/qb/webhook', type='http', auth='none', csrf=False, methods=['POST'])
    def webhook_handler(self, **kwargs):
        """
        Receive webhook notifications from QuickBooks Online.
        Supports both CloudEvents and legacy payload formats.
        Returns 200 immediately; processing is async via queue.
        """
        body = request.httprequest.get_data(as_text=True)

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            _logger.warning('Invalid JSON in webhook payload')
            return Response('OK', status=200)

        # Determine format: CloudEvents (list of events) or legacy
        if isinstance(payload, list):
            self._handle_cloud_events(payload, body)
        elif isinstance(payload, dict) and 'eventNotifications' in payload:
            self._handle_legacy_events(payload, body)
        else:
            _logger.warning('Unknown webhook format')

        return Response('OK', status=200)

    def _verify_signature(self, body, config):
        """Verify the HMAC-SHA256 signature from Intuit."""
        signature = request.httprequest.headers.get(
            'intuit-signature', ''
        )
        if not signature or not config.webhook_verifier_token:
            return False

        expected = hmac.new(
            config.webhook_verifier_token.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).digest()

        import base64
        expected_b64 = base64.b64encode(expected).decode('utf-8')
        return hmac.compare_digest(signature, expected_b64)

    def _find_config_by_realm(self, realm_id):
        """Find QB config for a given realm/account ID."""
        Config = request.env['quickbooks.config'].sudo()
        return Config.search([
            ('realm_id', '=', realm_id),
            ('state', '=', 'connected'),
        ], limit=1)

    # ---- CloudEvents format ----

    def _handle_cloud_events(self, events, raw_body):
        """Process CloudEvents-format webhook notifications."""
        for event in events:
            realm_id = event.get('intuitaccountid', '')
            config = self._find_config_by_realm(realm_id)
            if not config:
                _logger.warning(
                    'No config for realm %s in CloudEvents webhook', realm_id,
                )
                continue

            if not self._verify_signature(raw_body, config):
                _logger.warning('Signature verification failed for realm %s', realm_id)
                continue

            event_type = event.get('type', '')
            entity_id = event.get('intuitentityid', '')
            event_id = event.get('id', '')

            mapping = CLOUD_EVENT_TYPE_MAP.get(event_type)
            if not mapping:
                _logger.debug('Unhandled CloudEvent type: %s', event_type)
                continue

            entity_type, operation = mapping
            idempotency_key = 'ce_%s' % event_id if event_id else None

            request.env['quickbooks.sync.queue'].sudo().enqueue(
                entity_type=entity_type,
                direction='pull',
                operation=operation,
                qb_entity_id=entity_id,
                company=config.company_id,
                idempotency_key=idempotency_key,
            )

        _logger.info('Processed %d CloudEvents webhook events', len(events))

    # ---- Legacy format (pre-CloudEvents) ----

    def _handle_legacy_events(self, payload, raw_body):
        """Process legacy-format webhook notifications."""
        for notification in payload.get('eventNotifications', []):
            realm_id = notification.get('realmId', '')
            config = self._find_config_by_realm(realm_id)
            if not config:
                _logger.warning(
                    'No config for realm %s in legacy webhook', realm_id,
                )
                continue

            if not self._verify_signature(raw_body, config):
                _logger.warning('Signature verification failed for realm %s', realm_id)
                continue

            entities = (
                notification.get('dataChangeEvent', {}).get('entities', [])
            )
            for entity in entities:
                name = entity.get('name', '')
                entity_type = LEGACY_ENTITY_MAP.get(name)
                if not entity_type:
                    _logger.debug('Unhandled legacy entity: %s', name)
                    continue

                operation_str = entity.get('operation', 'Update').lower()
                if operation_str not in ('create', 'update', 'delete'):
                    operation_str = 'update'

                entity_id = str(entity.get('id', ''))
                last_updated = (
                    entity.get('lastUpdated') or
                    entity.get('lastUpdatedTime') or
                    entity.get('LastUpdatedTime') or
                    ''
                )
                idempotency_key = 'legacy_%s_%s_%s_%s' % (
                    realm_id, entity_type, entity_id, last_updated,
                )

                request.env['quickbooks.sync.queue'].sudo().enqueue(
                    entity_type=entity_type,
                    direction='pull',
                    operation=operation_str,
                    qb_entity_id=entity_id,
                    company=config.company_id,
                    idempotency_key=idempotency_key,
                )

        _logger.info('Processed legacy webhook payload')
