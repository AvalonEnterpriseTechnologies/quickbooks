"""Coverage for the QBO ApplicationAuthorizationFailed (003100) handling.

When Intuit revokes the OAuth grant for a realm, every subsequent REST
call returns ``403 + Fault.Error[0].code='3100'`` — the same response
even after a token refresh, because token refresh cannot recover from
a revoked grant. Before this feature, run_full_sync would fire that
doomed request for all 25 entity stages, leaving 25 identical error
log lines and no actionable signal to the operator.

These tests pin down the new behaviour:

  * ``_is_application_auth_failed`` recognises every QBO casing
    (capital ``Fault`` v3 REST, lowercase ``fault`` from batch/CDC,
    even a corrupt body that still contains the magic string).
  * ``_execute`` raises ``QBApiAuthorizationRevokedError`` and flips
    ``quickbooks.config.state`` to ``error`` with a remediation
    message, and posts a chatter note exactly once even across
    repeated calls.
  * ``run_full_sync`` short-circuits — the first stage that hits the
    003100 stops the loop instead of failing every subsequent stage.
  * ``action_test_connection`` re-raises the remediation as a
    ``UserError`` so it surfaces on the Settings panel.
"""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from ..services.qb_api_client import (
    QBApiAuthorizationRevokedError,
    _QBClient,
)
from .common import QuickbooksTestCommon


AUTH_FAILED_BODY = (
    '{"warnings":null,"intuitObject":null,"fault":{"error":'
    '[{"message":"message=ApplicationAuthorizationFailed; '
    'errorCode=003100; statusCode=403","detail":"","code":"3100",'
    '"element":null}],"type":"SERVICE"}}'
)


def _mock_403_response(body=AUTH_FAILED_BODY):
    resp = MagicMock()
    resp.status_code = 403
    resp.text = body
    resp.json.return_value = {
        'fault': {
            'error': [{
                'message': (
                    'message=ApplicationAuthorizationFailed; '
                    'errorCode=003100; statusCode=403'
                ),
                'detail': '',
                'code': '3100',
                'element': None,
            }],
            'type': 'SERVICE',
        },
    }
    return resp


def _mock_ok_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = ''
    resp.json.return_value = payload
    return resp


@tagged('post_install', '-at_install')
class TestApplicationAuthFailedDetection(QuickbooksTestCommon):

    def test_detects_lowercase_fault_with_code_3100(self):
        resp = _mock_403_response()
        self.assertTrue(_QBClient._is_application_auth_failed(resp))

    def test_detects_capitalized_fault_with_code_3100(self):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = ''
        resp.json.return_value = {
            'Fault': {
                'Error': [{'code': '3100', 'Message': 'auth failed'}],
                'type': 'SERVICE',
            },
        }
        self.assertTrue(_QBClient._is_application_auth_failed(resp))

    def test_detects_via_text_search_when_json_is_unparseable(self):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = 'garbage ApplicationAuthorizationFailed garbage'
        resp.json.side_effect = ValueError('not json')
        self.assertTrue(_QBClient._is_application_auth_failed(resp))

    def test_rejects_unrelated_400_response(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = ''
        resp.json.return_value = {
            'Fault': {
                'Error': [{'code': '2020', 'Message': 'Required param missing'}],
            },
        }
        self.assertFalse(_QBClient._is_application_auth_failed(resp))


@tagged('post_install', '-at_install')
class TestExecuteRaisesAuthorizationRevoked(QuickbooksTestCommon):
    """End-to-end test for _execute() seeing a 003100 response."""

    def _patched_client(self):
        """Build a real _QBClient with the auth service short-circuited.

        We don't want the test to touch encrypted tokens / refresh
        logic — only the 403-handling branch matters here.
        """
        client = self.env['qb.api.client'].get_client(self.config)
        client._auth_service = MagicMock()
        client._auth_service.ensure_token_valid.return_value = 'fake-token'
        client._auth_service.refresh_token.return_value = None
        client._wait_for_rate_limit = lambda: None
        return client

    def test_execute_raises_and_flips_state_to_error(self):
        client = self._patched_client()
        self.assertEqual(self.config.state, 'connected')

        with patch(
            'odoo.addons.quickbooks_api_connector.services.qb_api_client.'
            'http_requests'
        ) as http:
            http.request.return_value = _mock_403_response()
            with self.assertRaises(QBApiAuthorizationRevokedError):
                client._execute('GET', 'companyinfo/%s' % self.config.realm_id)

        self.config.invalidate_recordset(['state', 'error_message'])
        self.assertEqual(self.config.state, 'error')
        self.assertIn('revoked', (self.config.error_message or '').lower())
        self.assertIn('Connect to QuickBooks',
                      self.config.error_message or '')

    def test_execute_marks_state_only_once_across_repeated_403s(self):
        """A storm of 003100 responses must not generate 25 chatter
        posts — the helper should detect 'already marked' and no-op."""
        client = self._patched_client()
        with patch(
            'odoo.addons.quickbooks_api_connector.services.qb_api_client.'
            'http_requests'
        ) as http:
            http.request.return_value = _mock_403_response()
            for _ in range(3):
                try:
                    client._execute('GET', 'companyinfo/x')
                except QBApiAuthorizationRevokedError:
                    pass

        # Count chatter messages whose subject is the auth-revoked notice.
        messages = self.env['mail.message'].search([
            ('model', '=', 'quickbooks.config'),
            ('res_id', '=', self.config.id),
            ('subject', '=', 'QuickBooks Authorization Revoked'),
        ])
        self.assertEqual(
            len(messages), 1,
            'auth-revoked notice must be posted exactly once even after '
            'repeated 003100 responses',
        )


@tagged('post_install', '-at_install')
class TestRunFullSyncShortCircuit(QuickbooksTestCommon):
    """run_full_sync must stop iterating entities after the first 003100
    so the operator doesn't get 25 cascading errors in their logs.
    """

    def _drive_run_full_sync(self, raise_on_entity):
        """Run engine.run_full_sync with every entity service stubbed.

        Each service in ENTITY_SERVICE_MAP gets its ``pull_all`` /
        ``push_all`` replaced with a stub that records the entity_type
        in ``stages_attempted``. The stub also raises
        QBApiAuthorizationRevokedError when entity_type matches
        ``raise_on_entity`` so we can prove the loop short-circuits.
        """
        from odoo.addons.quickbooks_api_connector.services.qb_sync_engine \
            import ENTITY_SERVICE_MAP
        engine = self.env['qb.sync.engine']
        stages_attempted = []

        def _make_pull(_service_name):
            def _pull(self_inner, client, config, entity_type):
                stages_attempted.append(entity_type)
                if entity_type == raise_on_entity:
                    raise QBApiAuthorizationRevokedError(
                        403, AUTH_FAILED_BODY, 'http://x/query',
                    )
            return _pull

        def _push(self_inner, client, config, entity_type):
            pass

        patches = []
        for service_name in set(ENTITY_SERVICE_MAP.values()):
            try:
                SvcClass = type(self.env[service_name])
            except KeyError:
                continue
            patches.append(patch.object(
                SvcClass, 'pull_all', _make_pull(service_name),
            ))
            patches.append(patch.object(SvcClass, 'push_all', _push))

        Client = type(self.env['qb.api.client'])
        patches.append(patch.object(
            Client, 'get_client', return_value=self._mock_client(),
        ))
        patches.append(patch.object(
            engine, '_collect_cdc_records', return_value={},
        ))

        for p in patches:
            p.start()
        try:
            engine.run_full_sync(self.config)
        finally:
            for p in patches:
                p.stop()
        return stages_attempted

    def test_run_full_sync_stops_after_first_auth_revoked(self):
        # account is the third stage in entity_order; everything before
        # it (company_info, exchange_rate) should still run, everything
        # after must NOT.
        attempted = self._drive_run_full_sync(raise_on_entity='account')
        self.assertIn('company_info', attempted)
        self.assertIn('account', attempted)
        self.assertNotIn(
            'invoice', attempted,
            'run_full_sync must short-circuit after the first 003100; '
            'reached: %s' % attempted,
        )
        self.assertNotIn('payment', attempted)
        self.assertNotIn('journal_entry', attempted)

    def test_run_full_sync_does_not_bump_last_sync_when_auth_revoked(self):
        """last_sync_date is the CDC watermark; bumping it on a failed
        run would silently drop everything that happens between now and
        the eventual reconnect."""
        self.config.last_sync_date = False
        self._drive_run_full_sync(raise_on_entity='account')
        self.config.invalidate_recordset(['last_sync_date'])
        self.assertFalse(
            self.config.last_sync_date,
            'last_sync_date must not be bumped when the run aborted on '
            'a revoked authorization',
        )


@tagged('post_install', '-at_install')
class TestActionTestConnectionFriendlyError(QuickbooksTestCommon):

    def test_action_test_connection_translates_403_to_user_error(self):
        client = self.env['qb.api.client'].get_client(self.config)
        client._auth_service = MagicMock()
        client._auth_service.ensure_token_valid.return_value = 'fake-token'
        client._auth_service.refresh_token.return_value = None
        client._wait_for_rate_limit = lambda: None

        with patch.object(
            type(self.env['qb.api.client']),
            'get_client',
            return_value=client,
        ), patch(
            'odoo.addons.quickbooks_api_connector.services.qb_api_client.'
            'http_requests'
        ) as http:
            http.request.return_value = _mock_403_response()
            with self.assertRaises(UserError) as ctx:
                self.config.action_test_connection()

        message = str(ctx.exception)
        self.assertIn('revoked', message.lower())
        self.assertIn('Connect to QuickBooks', message)
