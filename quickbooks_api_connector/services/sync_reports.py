import logging
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)

REPORT_TYPES = (
    'BalanceSheet',
    'ProfitAndLoss',
    'TrialBalance',
    'GeneralLedger',
    'AgedReceivables',
    'AgedReceivableDetail',
    'AgedPayables',
    'AgedPayableDetail',
    'InventoryValuationSummary',
    'SalesTaxLiabilityReport',
    'WorkersCompensation',
)

ACCOUNT_REPORT_TYPES = ('BalanceSheet', 'TrialBalance')
PARTNER_BALANCE_REPORTS = (
    'AgedReceivables',
    'AgedReceivableDetail',
    'AgedPayables',
    'AgedPayableDetail',
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
        for method in self._report_methods(config):
            for report_type in REPORT_TYPES:
                for window_start, window_end in self._date_windows(
                    start_date, end_date, config,
                ):
                    payload = self._fetch_report(
                        client, config, report_type, window_start, window_end, method,
                    )
                    rows = self._normalized_rows(payload)
                    total_rows += len(rows)
                    self._store_derived_balances(
                        config, report_type, window_start, window_end, payload, method, rows,
                    )
        return {'rows': total_rows}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping report push_all; QBO reports are read-only.')
        return {}

    def _fetch_report(self, client, config, report_type, start_date, end_date, method=None):
        params = {
            'start_date': fields.Date.to_string(start_date),
            'end_date': fields.Date.to_string(end_date),
            'accounting_method': method or getattr(config, 'reports_method', 'Accrual') or 'Accrual',
        }
        testing = True if getattr(config, 'reports_use_v2_now', False) else None
        return client.reports(report_type, params=params, testing_migration=testing)

    def _store_derived_balances(self, config, report_type, start_date, end_date, payload, method, rows):
        if report_type in ACCOUNT_REPORT_TYPES:
            self._store_account_balances(config, report_type, start_date, end_date, payload, method, rows)

    def _store_account_balances(self, config, report_type, start_date, end_date, payload, method, rows):
        Variance = self.env['qb.balance.variance'].sudo()
        Variance.search([
            ('company_id', '=', config.company_id.id),
            ('report_type', '=', report_type),
            ('period_start', '=', start_date),
            ('period_end', '=', end_date),
            ('accounting_method', '=', method or getattr(config, 'reports_method', 'Accrual') or 'Accrual'),
        ]).unlink()
        currency = config.company_id.currency_id
        for row in rows:
            name = row.get('label')
            amount = row.get('amount')
            if not name or amount is None or self._is_computed_report_row(row):
                continue
            account = self._find_account(config, row)
            if not account and not row.get('id'):
                continue
            if account:
                account.write({'qb_current_balance': amount})
            Variance.create({
                'company_id': config.company_id.id,
                'account_id': account.id if account else False,
                'label': name,
                'report_type': report_type,
                'period_start': start_date,
                'period_end': end_date,
                'accounting_method': method or getattr(config, 'reports_method', 'Accrual') or 'Accrual',
                'qb_amount': amount,
                'odoo_amount': self._odoo_account_balance(account, end_date) if account else 0.0,
                'threshold_breached': abs(amount) > (getattr(config, 'balance_variance_threshold', 0.0) or 0.0),
                'raw_json': payload,
                'currency_id': currency.id,
            })

    def _find_account(self, config, row):
        qb_id = row.get('id')
        matcher = self.env['qb.record.matcher'].sudo()
        qbo_hint = self._account_hint(row)
        if qb_id or qbo_hint.get('Name'):
            account = matcher.find_odoo_match_for_account(
                qbo_hint, config.company_id,
            )
            if account:
                return account
        Account = self.env['account.account'].sudo()
        domain = [('name', '=', row.get('label'))]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', config.company_id.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', 'in', [config.company_id.id, False]))
        return Account.search(domain, limit=1)

    def _find_partner(self, kind, row):
        field = 'qb_customer_id' if kind == 'customer' else 'qb_vendor_id'
        Partner = self.env['res.partner'].sudo()
        if row.get('id'):
            partner = Partner.search([(field, '=', row.get('id'))], limit=1)
            if partner:
                return partner
        rank_field = 'customer_rank' if kind == 'customer' else 'supplier_rank'
        return Partner.search([
            (rank_field, '>', 0),
            ('name', '=', row.get('label')),
        ], limit=1)

    def _find_product(self, row):
        Product = self.env['product.product'].sudo()
        if row.get('id'):
            product = Product.search([('qb_item_id', '=', row.get('id'))], limit=1)
            if product:
                return product
        return Product.search([('name', '=', row.get('label'))], limit=1)

    def _odoo_account_balance(self, account, end_date):
        if not account:
            return 0.0
        domain = [
            ('account_id', '=', account.id),
            ('date', '<=', end_date),
            ('parent_state', '=', 'posted'),
        ]
        return sum(self.env['account.move.line'].sudo().search(domain).mapped('balance'))

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
            'id': first.get('id') or '',
            'label': label or ' / '.join([p for p in path if p]),
            'path': path,
            'amount': amount,
            'columns': col_data,
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
    def _numeric_values(col_data):
        values = []
        for col in col_data or []:
            raw = col.get('value')
            if raw in (None, ''):
                continue
            try:
                values.append(float(str(raw).replace(',', '').replace('$', '')))
            except (TypeError, ValueError):
                continue
        return values

    @staticmethod
    def _aging_buckets(amounts):
        values = list(amounts or [])
        if len(values) >= 6:
            bucket_values = values[-6:]
            return {
                'current': bucket_values[0],
                '1_30': bucket_values[1],
                '31_60': bucket_values[2],
                '61_90': bucket_values[3],
                'over_90': bucket_values[4],
                'total': bucket_values[5],
            }
        total = values[-1] if values else 0.0
        return {
            'current': total,
            '1_30': 0.0,
            '31_60': 0.0,
            '61_90': 0.0,
            'over_90': 0.0,
            'total': total,
        }

    @staticmethod
    def _is_computed_report_row(row):
        label = str(row.get('label') or '').strip().casefold()
        if not label:
            return True
        computed_prefixes = ('total ', 'net ', 'gross ', 'subtotal')
        computed_labels = ('net income', 'net earnings')
        return label in computed_labels or label.startswith(computed_prefixes)

    @staticmethod
    def _account_hint(row):
        path = ' '.join(row.get('path') or []).casefold()
        label = row.get('label') or row.get('id') or ''
        account_type = ''
        if 'accounts receivable' in path:
            account_type = 'Accounts Receivable'
        elif 'accounts payable' in path:
            account_type = 'Accounts Payable'
        elif 'bank' in path or 'cash' in path:
            account_type = 'Bank'
        elif 'credit card' in path:
            account_type = 'Credit Card'
        elif 'asset' in path:
            account_type = 'Other Current Asset'
        elif 'liabilit' in path:
            account_type = 'Other Current Liability'
        elif 'equity' in path:
            account_type = 'Equity'
        elif 'income' in path or 'revenue' in path:
            account_type = 'Income'
        elif 'expense' in path or 'cost of goods' in path:
            account_type = 'Expense'
        return {
            'Id': row.get('id') or '',
            'Name': label,
            'AccountType': account_type,
        }

    @staticmethod
    def _schema_version(payload):
        header = payload.get('Header') or {}
        version = str(header.get('ReportBasis') or payload.get('schemaVersion') or '').lower()
        return 'v2' if 'v2' in version or payload.get('ColumnsV2') else 'v1'

    @staticmethod
    def _report_methods(config):
        strategy = getattr(config, 'reports_accounting_methods', '') or ''
        if strategy == 'both':
            return ('Accrual', 'Cash')
        if strategy == 'cash':
            return ('Cash',)
        if strategy == 'accrual':
            return ('Accrual',)
        return (getattr(config, 'reports_method', 'Accrual') or 'Accrual',)

    @staticmethod
    def _date_windows(start_date, end_date, config=None):
        current = fields.Date.to_date(start_date)
        end = fields.Date.to_date(end_date)
        strategy = getattr(config, 'reports_window_strategy', 'six_month') if config else 'six_month'
        month_step = {'monthly': 1, 'quarterly': 3}.get(strategy, 6)
        while current <= end:
            window_end = min(
                QBSyncReports._add_months(current, month_step) - timedelta(days=1),
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

