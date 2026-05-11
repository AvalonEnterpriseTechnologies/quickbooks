import logging
from collections import defaultdict
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)

REPORT_TYPES = (
    'BalanceSheet',
    'ProfitAndLoss',
    'TrialBalance',
    'GeneralLedger',
    'WorkersCompensation',
)


class QBSyncReports(models.AbstractModel):
    _name = 'qb.sync.reports'
    _description = 'QuickBooks Reports Sync'

    def pull(self, client, config, job):
        return self.pull_all(client, config, 'report')

    def push(self, client, config, job):
        _logger.info('QuickBooks reports are read-only.')
        return {}

    def pull_all(self, client, config, entity_type):
        months = max(getattr(config, 'reports_history_months', 12) or 12, 1)
        end_date = fields.Date.context_today(self)
        start_date = self._add_months(end_date, -months)
        total_rows = 0
        for report_type in REPORT_TYPES:
            for window_start, window_end in self._date_windows(start_date, end_date):
                payload = self._fetch_report(client, config, report_type, window_start, window_end)
                snapshot = self._store_snapshot(
                    config, report_type, window_start, window_end, payload,
                )
                rows = self._normalized_rows(payload)
                total_rows += len(rows)
                self._store_derived_balances(config, snapshot, report_type, rows)
        self._prune_snapshots(config)
        return {'rows': total_rows}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping report push_all; QBO reports are read-only.')
        return {}

    def _fetch_report(self, client, config, report_type, start_date, end_date):
        params = {
            'start_date': fields.Date.to_string(start_date),
            'end_date': fields.Date.to_string(end_date),
            'accounting_method': getattr(config, 'reports_method', 'Accrual') or 'Accrual',
        }
        testing = True if getattr(config, 'reports_use_v2_now', False) else None
        return client.reports(report_type, params=params, testing_migration=testing)

    def _store_snapshot(self, config, report_type, start_date, end_date, payload):
        rows = self._normalized_rows(payload)
        schema_version = self._schema_version(payload)
        Snapshot = self.env['quickbooks.report.snapshot'].sudo()
        vals = {
            'company_id': config.company_id.id,
            'report_type': report_type,
            'period_start': start_date,
            'period_end': end_date,
            'accounting_method': getattr(config, 'reports_method', 'Accrual') or 'Accrual',
            'schema_version': schema_version,
            'raw_json': payload,
            'fetched_at': fields.Datetime.now(),
            'row_count': len(rows),
        }
        existing = Snapshot.search([
            ('company_id', '=', config.company_id.id),
            ('report_type', '=', report_type),
            ('period_start', '=', start_date),
            ('period_end', '=', end_date),
            ('accounting_method', '=', vals['accounting_method']),
            ('schema_version', '=', schema_version),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Snapshot.create(vals)

    def _store_derived_balances(self, config, snapshot, report_type, rows):
        if report_type in ('BalanceSheet', 'TrialBalance'):
            self._store_account_balances(config, snapshot, report_type, rows)
        elif report_type == 'GeneralLedger':
            self._store_journal_balances(config, snapshot, rows)

    def _store_account_balances(self, config, snapshot, report_type, rows):
        Balance = self.env['quickbooks.account.balance'].sudo()
        Balance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        currency = config.company_id.currency_id
        for row in rows:
            name = row.get('label')
            amount = row.get('amount')
            if not name or amount is None:
                continue
            account = self._find_account(config, row)
            Balance.create({
                'company_id': config.company_id.id,
                'account_id': account.id if account else False,
                'qb_account_id': row.get('id') or '',
                'account_name': name,
                'report_type': report_type,
                'period_end': snapshot.period_end,
                'accounting_method': snapshot.accounting_method,
                'debit_balance': amount if amount >= 0 else 0.0,
                'credit_balance': abs(amount) if amount < 0 else 0.0,
                'balance': amount,
                'currency_id': currency.id,
                'snapshot_id': snapshot.id,
            })

    def _store_journal_balances(self, config, snapshot, rows):
        Balance = self.env['quickbooks.journal.balance'].sudo()
        Balance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        grouped = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0, 'name': ''})
        for row in rows:
            code = row.get('journal_code') or row.get('label') or 'General'
            grouped[code]['name'] = row.get('journal_name') or code
            amount = row.get('amount') or 0.0
            if amount >= 0:
                grouped[code]['debit'] += amount
            else:
                grouped[code]['credit'] += abs(amount)
        currency = config.company_id.currency_id
        for code, totals in grouped.items():
            Balance.create({
                'company_id': config.company_id.id,
                'journal_code': code,
                'journal_name': totals['name'],
                'period_end': snapshot.period_end,
                'accounting_method': snapshot.accounting_method,
                'debit_balance': totals['debit'],
                'credit_balance': totals['credit'],
                'balance': totals['debit'] - totals['credit'],
                'currency_id': currency.id,
                'snapshot_id': snapshot.id,
            })

    def _find_account(self, config, row):
        qb_id = row.get('id')
        Account = self.env['account.account'].sudo()
        if qb_id:
            account = Account.search([
                ('company_ids', 'in', config.company_id.id),
                ('qb_account_id', '=', qb_id),
            ], limit=1)
            if account:
                return account
        return Account.search([
            ('company_ids', 'in', config.company_id.id),
            ('name', '=', row.get('label')),
        ], limit=1)

    def _normalized_rows(self, payload):
        rows = []
        self._walk_rows(payload.get('Rows', {}).get('Row', []), rows, [])
        return rows

    def _walk_rows(self, qbo_rows, out, path):
        for row in qbo_rows or []:
            header = row.get('Header', {})
            label = self._first_col_value(header.get('ColData')) or row.get('group')
            current_path = path + ([label] if label else [])
            if row.get('Rows'):
                self._walk_rows(row.get('Rows', {}).get('Row', []), out, current_path)
            if row.get('ColData'):
                normalized = self._row_from_col_data(row.get('ColData'), current_path)
                if normalized:
                    out.append(normalized)

    def _row_from_col_data(self, col_data, path):
        label = self._first_col_value(col_data)
        amount = self._last_numeric_value(col_data)
        if label is None and amount is None:
            return {}
        first = col_data[0] if col_data else {}
        return {
            'id': first.get('id') or first.get('value'),
            'label': label or ' / '.join([p for p in path if p]),
            'path': path,
            'amount': amount,
            'journal_code': self._value_at(col_data, 1),
            'journal_name': self._value_at(col_data, 1),
        }

    @staticmethod
    def _first_col_value(col_data):
        for col in col_data or []:
            if col.get('value') not in (None, ''):
                return col.get('value')
        return None

    @staticmethod
    def _last_numeric_value(col_data):
        for col in reversed(col_data or []):
            try:
                value = str(col.get('value', '')).replace(',', '')
                if value:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _value_at(col_data, index):
        if len(col_data or []) > index:
            return col_data[index].get('value')
        return ''

    @staticmethod
    def _schema_version(payload):
        header = payload.get('Header') or {}
        version = str(header.get('ReportBasis') or payload.get('schemaVersion') or '').lower()
        return 'v2' if 'v2' in version or payload.get('ColumnsV2') else 'v1'

    @staticmethod
    def _date_windows(start_date, end_date):
        current = fields.Date.to_date(start_date)
        end = fields.Date.to_date(end_date)
        while current <= end:
            window_end = min(
                QBSyncReports._add_months(current, 6) - timedelta(days=1),
                end,
            )
            yield current, window_end
            current = window_end + timedelta(days=1)

    @staticmethod
    def _add_months(value, months):
        value = fields.Date.to_date(value)
        month = value.month - 1 + months
        year = value.year + month // 12
        month = month % 12 + 1
        days_in_month = [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
        ][month - 1]
        return value.replace(year=year, month=month, day=min(value.day, days_in_month))

    def _prune_snapshots(self, config):
        keep = max(getattr(config, 'reports_keep_n', 12) or 12, 1)
        Snapshot = self.env['quickbooks.report.snapshot'].sudo()
        for report_type in REPORT_TYPES:
            snapshots = Snapshot.search([
                ('company_id', '=', config.company_id.id),
                ('report_type', '=', report_type),
            ], order='period_end desc, fetched_at desc')
            old = snapshots[keep:]
            if old:
                old.unlink()
