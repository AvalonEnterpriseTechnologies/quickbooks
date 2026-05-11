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
                    snapshot = self._store_snapshot(
                        config, report_type, window_start, window_end, payload, method,
                    )
                    rows = self._normalized_rows(payload)
                    total_rows += len(rows)
                    self._store_derived_balances(config, snapshot, report_type, rows)
                    self._store_report_rows(config, snapshot, payload)
        self._prune_snapshots(config)
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

    def _store_snapshot(self, config, report_type, start_date, end_date, payload, method=None):
        rows = self._normalized_rows(payload)
        schema_version = self._schema_version(payload)
        Snapshot = self.env['quickbooks.report.snapshot'].sudo()
        vals = {
            'company_id': config.company_id.id,
            'report_type': report_type,
            'period_start': start_date,
            'period_end': end_date,
            'accounting_method': method or getattr(config, 'reports_method', 'Accrual') or 'Accrual',
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
        if report_type in ACCOUNT_REPORT_TYPES:
            self._store_account_balances(config, snapshot, report_type, rows)
        elif report_type == 'GeneralLedger':
            self._store_journal_balances(config, snapshot, rows)
        elif report_type in PARTNER_BALANCE_REPORTS:
            self._store_partner_balances(config, snapshot, report_type, rows)
        elif report_type == 'InventoryValuationSummary':
            self._store_inventory_balances(config, snapshot, rows)
        elif report_type == 'SalesTaxLiabilityReport':
            self._store_tax_liabilities(config, snapshot, rows)

    def _store_report_rows(self, config, snapshot, payload):
        ReportRow = self.env['quickbooks.report.row'].sudo()
        ReportRow.search([('snapshot_id', '=', snapshot.id)]).unlink()
        sequence = {'value': 0}
        self._create_report_rows(
            config=config,
            snapshot=snapshot,
            qbo_rows=payload.get('Rows', {}).get('Row', []),
            parent=False,
            path=[],
            level=0,
            sequence=sequence,
        )

    def _create_report_rows(self, config, snapshot, qbo_rows, parent, path, level, sequence):
        ReportRow = self.env['quickbooks.report.row'].sudo()
        for row in qbo_rows or []:
            header = row.get('Header') or {}
            summary = row.get('Summary') or {}
            label = (
                self._first_col_value(header.get('ColData'))
                or row.get('group')
                or self._first_col_value(row.get('ColData'))
                or self._first_col_value(summary.get('ColData'))
            )
            current_parent = parent
            current_path = path
            if label:
                sequence['value'] += 10
                col_data = row.get('ColData') or summary.get('ColData') or header.get('ColData')
                first = col_data[0] if col_data else {}
                values = {
                    'company_id': config.company_id.id,
                    'snapshot_id': snapshot.id,
                    'parent_id': parent.id if parent else False,
                    'sequence': sequence['value'],
                    'level': level,
                    'path': ' / '.join(path + [label]),
                    'label': label,
                    'amount': self._last_numeric_value(col_data) or 0.0,
                    'is_total': bool(summary.get('ColData')) or str(label).lower().startswith('total'),
                    'is_section': bool(row.get('Rows')),
                    'qb_account_id': first.get('id') or '',
                    'account_id': self._find_account(config, {
                        'id': first.get('id') or '',
                        'label': label,
                        'path': path,
                    }).id or False,
                    'currency_id': config.company_id.currency_id.id,
                }
                current_parent = ReportRow.create(values)
                current_path = path + [label]
            if row.get('Rows'):
                self._create_report_rows(
                    config, snapshot, row.get('Rows', {}).get('Row', []),
                    current_parent, current_path, level + 1, sequence,
                )
            if summary.get('ColData') and not (
                label and self._first_col_value(summary.get('ColData')) == label
            ):
                summary_label = self._first_col_value(summary.get('ColData')) or (
                    'Total %s' % (label or 'Section')
                )
                sequence['value'] += 10
                first = summary.get('ColData')[0] if summary.get('ColData') else {}
                ReportRow.create({
                    'company_id': config.company_id.id,
                    'snapshot_id': snapshot.id,
                    'parent_id': current_parent.id if current_parent else False,
                    'sequence': sequence['value'],
                    'level': level + 1,
                    'path': ' / '.join(current_path + [summary_label]),
                    'label': summary_label,
                    'amount': self._last_numeric_value(summary.get('ColData')) or 0.0,
                    'is_total': True,
                    'is_section': False,
                    'qb_account_id': first.get('id') or '',
                    'currency_id': config.company_id.currency_id.id,
                })

    def _store_account_balances(self, config, snapshot, report_type, rows):
        Balance = self.env['quickbooks.account.balance'].sudo()
        Balance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        currency = config.company_id.currency_id
        for row in rows:
            name = row.get('label')
            amount = row.get('amount')
            if not name or amount is None or self._is_computed_report_row(row):
                continue
            account = self._find_account(config, row)
            if not account and not row.get('id'):
                continue
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
        _logger.info(
            'Stored GeneralLedger snapshot %s as report rows only; GL row layouts '
            'are not reliable journal-balance sources.',
            snapshot.id,
        )

    def _store_partner_balances(self, config, snapshot, report_type, rows):
        Balance = self.env['quickbooks.partner.balance'].sudo()
        Balance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        kind = 'customer' if 'Receivable' in report_type else 'vendor'
        currency = config.company_id.currency_id
        for row in rows:
            if self._is_computed_report_row(row):
                continue
            label = row.get('label')
            if not label:
                continue
            amounts = self._numeric_values(row.get('columns') or [])
            if not amounts:
                continue
            buckets = self._aging_buckets(amounts)
            partner = self._find_partner(kind, row)
            Balance.create({
                'company_id': config.company_id.id,
                'partner_id': partner.id if partner else False,
                'partner_name': label,
                'qb_customer_id': row.get('id') if kind == 'customer' else '',
                'qb_vendor_id': row.get('id') if kind == 'vendor' else '',
                'kind': kind,
                'period_end': snapshot.period_end,
                'total': buckets['total'],
                'bucket_current': buckets['current'],
                'bucket_1_30': buckets['1_30'],
                'bucket_31_60': buckets['31_60'],
                'bucket_61_90': buckets['61_90'],
                'bucket_over_90': buckets['over_90'],
                'currency_id': currency.id,
                'snapshot_id': snapshot.id,
            })

    def _store_inventory_balances(self, config, snapshot, rows):
        Balance = self.env['quickbooks.inventory.balance'].sudo()
        Balance.search([('snapshot_id', '=', snapshot.id)]).unlink()
        currency = config.company_id.currency_id
        for row in rows:
            if self._is_computed_report_row(row):
                continue
            label = row.get('label')
            if not label:
                continue
            values = self._numeric_values(row.get('columns') or [])
            if not values:
                continue
            product = self._find_product(row)
            qty = values[0] if len(values) >= 1 else 0.0
            avg_cost = values[-2] if len(values) >= 2 else 0.0
            value = values[-1]
            Balance.create({
                'company_id': config.company_id.id,
                'product_id': product.id if product else False,
                'product_name': label,
                'qb_item_id': row.get('id') or '',
                'period_end': snapshot.period_end,
                'qty_on_hand': qty,
                'avg_cost': avg_cost,
                'value': value,
                'currency_id': currency.id,
                'snapshot_id': snapshot.id,
            })

    def _store_tax_liabilities(self, config, snapshot, rows):
        Liability = self.env['quickbooks.tax.liability'].sudo()
        Liability.search([('snapshot_id', '=', snapshot.id)]).unlink()
        currency = config.company_id.currency_id
        for row in rows:
            if self._is_computed_report_row(row):
                continue
            label = row.get('label')
            values = self._numeric_values(row.get('columns') or [])
            if not label or not values:
                continue
            tax = self.env['account.tax'].sudo().search([
                ('company_id', '=', config.company_id.id),
                '|',
                ('qb_taxcode_id', '=', row.get('id') or ''),
                ('name', '=', label),
            ], limit=1)
            Liability.create({
                'company_id': config.company_id.id,
                'tax_id': tax.id if tax else False,
                'tax_agency': label,
                'period_start': snapshot.period_start,
                'period_end': snapshot.period_end,
                'taxable_amount': values[-2] if len(values) >= 2 else 0.0,
                'tax_amount': values[-1],
                'currency_id': currency.id,
                'snapshot_id': snapshot.id,
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
