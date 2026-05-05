import json
import logging
import time
import threading
from collections import deque

try:
    import requests as http_requests
except ImportError:
    http_requests = None

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QBT_BASE_URL = 'https://rest.tsheets.com/api/v1'
QBT_MAX_REQUESTS_PER_5MIN = 300
QBT_MAX_RETRIES_429 = 5


class QBTApiClient(models.AbstractModel):
    _name = 'qbt.api.client'
    _description = 'QuickBooks Time (TSheets) API Client'

    def get_client(self, config):
        return _QBTClient(self.env, config)


class _QBTClient:
    """Rate-limited HTTP client for the QuickBooks Time (TSheets) REST API."""

    _lock = threading.Lock()
    _request_timestamps: deque = deque()

    def __init__(self, env, config):
        self.env = env
        self.config = config
        self._base_url = QBT_BASE_URL

    def _get_access_token(self):
        token = self.config._decrypt(
            getattr(self.config, 'qbt_access_token_encrypted', '') or ''
        )
        if not token:
            auth_service = self.env['qb.auth.service']
            token = auth_service.ensure_token_valid(self.config)
        return token

    def _get_headers(self):
        return {
            'Authorization': 'Bearer %s' % self._get_access_token(),
            'Content-Type': 'application/json',
        }

    def _wait_for_rate_limit(self):
        with self._lock:
            now = time.time()
            window = 300
            while len(self._request_timestamps) >= QBT_MAX_REQUESTS_PER_5MIN:
                oldest = self._request_timestamps[0]
                if now - oldest > window:
                    self._request_timestamps.popleft()
                else:
                    wait = window - (now - oldest) + 0.1
                    _logger.debug('QBT rate limit: sleeping %.1fs', wait)
                    time.sleep(wait)
                    now = time.time()
            self._request_timestamps.append(now)

    def get(self, endpoint, params=None, retries=0):
        if http_requests is None:
            raise UserError('The "requests" library is required.')
        self._wait_for_rate_limit()
        url = '%s/%s' % (self._base_url, endpoint.lstrip('/'))
        resp = http_requests.get(
            url, headers=self._get_headers(), params=params, timeout=60,
        )
        if resp.status_code == 429:
            if retries >= QBT_MAX_RETRIES_429:
                raise UserError('QBT rate limit exceeded after %d retries.' % retries)
            _logger.warning('QBT 429 – backing off 60s')
            time.sleep(60)
            return self.get(endpoint, params, retries=retries + 1)
        if resp.status_code >= 400:
            raise UserError('QBT API error %d: %s' % (resp.status_code, resp.text[:200]))
        return resp.json()

    def post(self, endpoint, payload, retries=0):
        if http_requests is None:
            raise UserError('The "requests" library is required.')
        self._wait_for_rate_limit()
        url = '%s/%s' % (self._base_url, endpoint.lstrip('/'))
        resp = http_requests.post(
            url, json=payload, headers=self._get_headers(), timeout=60,
        )
        if resp.status_code == 429:
            if retries >= QBT_MAX_RETRIES_429:
                raise UserError('QBT rate limit exceeded after %d retries.' % retries)
            _logger.warning('QBT 429 – backing off 60s')
            time.sleep(60)
            return self.post(endpoint, payload, retries=retries + 1)
        if resp.status_code >= 400:
            raise UserError('QBT API error %d: %s' % (resp.status_code, resp.text[:200]))
        return resp.json()

    def get_timesheets(self, start_date=None, end_date=None, page=1):
        params = {'page': page}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        return self.get('timesheets', params=params)

    def get_jobcodes(self, page=1):
        return self.get('jobcodes', params={'page': page})

    def get_users(self, page=1):
        return self.get('users', params={'page': page})
