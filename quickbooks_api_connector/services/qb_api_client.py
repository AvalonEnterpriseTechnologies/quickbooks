import json
import logging
import time
import threading
from collections import defaultdict, deque
from datetime import timezone

try:
    import requests as http_requests
except ImportError:
    http_requests = None

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QBO_API_VERSION = 'v3'
MAX_REQUESTS_PER_MINUTE = 450  # headroom below 500 limit
MAX_CONCURRENT = 8
MAX_RETRIES_429 = 5
MAX_RETRIES_5XX = 3
QBO_DUPLICATE_ERROR_CODES = {'6240', '610', '6210', '6140', '6211', '6000', '6045'}


class QBApiClient(models.AbstractModel):
    _name = 'qb.api.client'
    _description = 'QuickBooks API Client'

    def get_client(self, config):
        """Return a configured _QBClient instance."""
        return _QBClient(self.env, config)

    @api.model
    def format_qbo_datetime(self, value):
        """Format an Odoo datetime as the UTC ISO string QBO query filters expect."""
        if not value:
            return ''
        dt_value = fields.Datetime.to_datetime(value)
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        else:
            dt_value = dt_value.astimezone(timezone.utc)
        return dt_value.strftime('%Y-%m-%dT%H:%M:%SZ')


class _QBClient:
    """Rate-limited HTTP client for the QBO REST API v3."""

    _locks = defaultdict(threading.Lock)
    _request_timestamps = defaultdict(deque)
    _semaphores = defaultdict(lambda: threading.Semaphore(MAX_CONCURRENT))

    def __init__(self, env, config):
        self.env = env
        self.config = config
        self._auth_service = env['qb.auth.service']
        self._base_url = self._auth_service.get_api_base_url(config)

    @property
    def _api_prefix(self):
        return '%s/%s/company/%s' % (
            self._base_url, QBO_API_VERSION, self.config.realm_id,
        )

    @staticmethod
    def _append_minor_version(url):
        sep = '&' if '?' in url else '?'
        return '%s%sminorversion=75' % (url, sep)

    def _get_headers(self, access_token):
        return {
            'Authorization': 'Bearer %s' % access_token,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    @property
    def _realm_key(self):
        return self.config.realm_id or 'unconfigured'

    def _wait_for_rate_limit(self):
        """Sliding-window rate limiter scoped to the QBO realm/company."""
        realm_key = self._realm_key
        timestamps = self._request_timestamps[realm_key]
        with self._locks[realm_key]:
            now = time.time()
            while len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
                oldest = timestamps[0]
                if now - oldest > 60:
                    timestamps.popleft()
                else:
                    wait = 60 - (now - oldest) + 0.1
                    _logger.debug('Rate limit: sleeping %.1fs', wait)
                    time.sleep(wait)
                    now = time.time()
            timestamps.append(now)

    def _execute(self, method, endpoint, payload=None, retries=0,
                 refreshed_after_401=False, server_retries=0):
        """Execute an API request with rate limiting and retry logic."""
        if http_requests is None:
            raise UserError(
                'The "requests" Python library is required for QuickBooks API calls. '
                'Install it with: pip install requests'
            )
        access_token = self._auth_service.ensure_token_valid(self.config)
        self._wait_for_rate_limit()

        url = '%s/%s' % (self._api_prefix, endpoint.lstrip('/'))
        url = self._append_minor_version(url)
        headers = self._get_headers(access_token)

        kwargs = {'headers': headers, 'timeout': 60}
        if payload is not None:
            kwargs['json'] = payload

        semaphore = self._semaphores[self._realm_key]
        semaphore.acquire()
        try:
            resp = http_requests.request(method, url, **kwargs)
        finally:
            semaphore.release()

        if resp.status_code == 429:
            if retries >= MAX_RETRIES_429:
                raise UserError('QBO rate limit exceeded after %d retries.' % retries)
            wait = min(2 ** retries * 5, 60)
            _logger.warning('429 from QBO – backing off %ds (attempt %d)', wait, retries + 1)
            time.sleep(wait)
            return self._execute(
                method, endpoint, payload, retries + 1,
                refreshed_after_401=refreshed_after_401,
                server_retries=server_retries,
            )

        if resp.status_code == 401:
            if refreshed_after_401:
                raise QBApiError(resp.status_code, resp.text[:2000], url)
            _logger.info('401 from QBO – refreshing token and retrying')
            self._auth_service.refresh_token(self.config)
            return self._execute(
                method, endpoint, payload, retries,
                refreshed_after_401=True, server_retries=server_retries,
            )

        if resp.status_code in (500, 502, 503, 504):
            if server_retries >= MAX_RETRIES_5XX:
                raise QBApiError(resp.status_code, resp.text[:2000], url)
            wait = min(2 ** server_retries * 5, 60)
            _logger.warning(
                'QBO server error %s – backing off %ds (attempt %d)',
                resp.status_code, wait, server_retries + 1,
            )
            time.sleep(wait)
            return self._execute(
                method, endpoint, payload, retries,
                refreshed_after_401=refreshed_after_401,
                server_retries=server_retries + 1,
            )

        if resp.status_code >= 400:
            error_detail = resp.text[:2000]
            _logger.error('QBO API error %s %s: %s', method, url, error_detail)
            if resp.status_code == 400 and self._is_duplicate_error(resp):
                raise QBApiDuplicateError(resp.status_code, error_detail, url)
            raise QBApiError(resp.status_code, error_detail, url)

        if resp.status_code == 204:
            return {}
        return resp.json()

    # ---- Convenience methods ----

    def get(self, endpoint):
        return self._execute('GET', endpoint)

    def post(self, endpoint, payload):
        return self._execute('POST', endpoint, payload)

    def query(self, query_string):
        """Run a QBO SQL-like query."""
        import urllib.parse
        encoded = urllib.parse.quote(query_string)
        return self._execute('GET', 'query?query=%s' % encoded)

    def read(self, entity_name, entity_id):
        return self._execute('GET', '%s/%s' % (entity_name.lower(), entity_id))

    def create(self, entity_name, payload):
        return self._execute('POST', entity_name.lower(), payload)

    def update(self, entity_name, payload):
        return self._execute('POST', entity_name.lower(), payload)

    def delete(self, entity_name, payload):
        return self._execute(
            'POST', '%s?operation=delete' % entity_name.lower(), payload,
        )

    def cdc(self, entities, changed_since):
        """Use Change Data Capture to fetch all changed entities since a timestamp.

        Args:
            entities: comma-separated entity names e.g. 'Customer,Invoice,Payment'
            changed_since: ISO datetime string e.g. '2026-01-01T00:00:00Z'
        Returns:
            dict mapping entity name -> list of changed records
        """
        import urllib.parse
        endpoint = 'cdc?entities=%s&changedSince=%s' % (
            urllib.parse.quote(entities),
            urllib.parse.quote(changed_since),
        )
        resp = self._execute('GET', endpoint)
        result = {}
        for entry in resp.get('CDCResponse', []):
            query_response = entry.get('QueryResponse', [])
            for qr in query_response:
                for key, records in qr.items():
                    if isinstance(records, list):
                        result.setdefault(key, []).extend(records)
        return result

    def query_all(self, entity_name, where_clause='', page_size=1000):
        """Page through all records of an entity type."""
        results = []
        start_position = 1
        while True:
            q = "SELECT * FROM %s" % entity_name
            if where_clause:
                q += " WHERE %s" % where_clause
            q += " STARTPOSITION %d MAXRESULTS %d" % (start_position, page_size)

            resp = self.query(q)
            response_key = 'QueryResponse'
            data = resp.get(response_key, {})
            records = data.get(entity_name, [])
            if not records:
                break
            results.extend(records)
            if len(records) < page_size:
                break
            start_position += page_size
        return results

    @staticmethod
    def _is_duplicate_error(resp):
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        errors = payload.get('Fault', {}).get('Error', [])
        for error in errors:
            code = str(error.get('code', ''))
            detail = '%s %s' % (error.get('Message', ''), error.get('Detail', ''))
            if code in QBO_DUPLICATE_ERROR_CODES or 'duplicate' in detail.lower():
                return True
        return 'duplicate' in resp.text.lower()


class QBApiError(Exception):
    """Raised when the QBO API returns an error response."""

    def __init__(self, status_code, detail, url=''):
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__('QBO API %d: %s' % (status_code, detail[:200]))


class QBApiDuplicateError(QBApiError):
    """Raised when QBO rejects a create because a matching record already exists."""
