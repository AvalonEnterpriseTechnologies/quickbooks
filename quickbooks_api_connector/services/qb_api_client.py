import json
import logging
import time
import threading
from collections import deque
from datetime import timedelta

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


class QBApiClient(models.AbstractModel):
    _name = 'qb.api.client'
    _description = 'QuickBooks API Client'

    def get_client(self, config):
        """Return a configured _QBClient instance."""
        return _QBClient(self.env, config)


class _QBClient:
    """Rate-limited HTTP client for the QBO REST API v3."""

    _lock = threading.Lock()
    _request_timestamps: deque = deque()
    _semaphore = threading.Semaphore(MAX_CONCURRENT)

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

    def _wait_for_rate_limit(self):
        """Sliding-window rate limiter."""
        with self._lock:
            now = time.time()
            while len(self._request_timestamps) >= MAX_REQUESTS_PER_MINUTE:
                oldest = self._request_timestamps[0]
                if now - oldest > 60:
                    self._request_timestamps.popleft()
                else:
                    wait = 60 - (now - oldest) + 0.1
                    _logger.debug('Rate limit: sleeping %.1fs', wait)
                    time.sleep(wait)
                    now = time.time()
            self._request_timestamps.append(now)

    def _execute(self, method, endpoint, payload=None, retries=0):
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

        self._semaphore.acquire()
        try:
            resp = http_requests.request(method, url, **kwargs)
        finally:
            self._semaphore.release()

        if resp.status_code == 429:
            if retries >= MAX_RETRIES_429:
                raise UserError('QBO rate limit exceeded after %d retries.' % retries)
            wait = min(2 ** retries * 5, 60)
            _logger.warning('429 from QBO – backing off %ds (attempt %d)', wait, retries + 1)
            time.sleep(wait)
            return self._execute(method, endpoint, payload, retries + 1)

        if resp.status_code == 401:
            _logger.info('401 from QBO – refreshing token and retrying')
            self._auth_service.refresh_token(self.config)
            return self._execute(method, endpoint, payload, retries)

        if resp.status_code >= 400:
            error_detail = resp.text[:2000]
            _logger.error('QBO API error %s %s: %s', method, url, error_detail)
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


class QBApiError(Exception):
    """Raised when the QBO API returns an error response."""

    def __init__(self, status_code, detail, url=''):
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__('QBO API %d: %s' % (status_code, detail[:200]))
