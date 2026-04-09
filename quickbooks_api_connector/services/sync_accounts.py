import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

QBO_ACCOUNT_TYPE_MAP = {
    'Bank': 'asset_cash',
    'Other Current Asset': 'asset_current',
    'Fixed Asset': 'asset_fixed',
    'Other Asset': 'asset_non_current',
    'Accounts Receivable': 'asset_receivable',
    'Equity': 'equity',
    'Expense': 'expense',
    'Other Expense': 'expense',
    'Cost of Goods Sold': 'expense_direct_cost',
    'Accounts Payable': 'liability_payable',
    'Credit Card': 'liability_credit_card',
    'Other Current Liability': 'liability_current',
    'Long Term Liability': 'liability_non_current',
    'Income': 'income',
    'Other Income': 'income_other',
}


class QBSyncAccounts(models.AbstractModel):
    _name = 'qb.sync.accounts'
    _description = 'QuickBooks Account Sync'

    def _qb_account_to_odoo(self, qb_data):
        """Map a QBO Account to Odoo account.account vals."""
        qb_type = qb_data.get('AccountType', '')
        odoo_type = QBO_ACCOUNT_TYPE_MAP.get(qb_type, 'asset_current')

        vals = {
            'name': qb_data.get('Name', ''),
            'code': qb_data.get('AcctNum') or str(qb_data.get('Id', '')),
            'account_type': odoo_type,
            'qb_account_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }

        if qb_data.get('Description'):
            vals['note'] = qb_data['Description']

        return vals

    def _odoo_to_qb_account(self, account):
        """Map Odoo account.account to QBO Account dict (primarily for ref)."""
        reverse_map = {v: k for k, v in QBO_ACCOUNT_TYPE_MAP.items()}
        qb_type = reverse_map.get(account.account_type, 'Expense')

        data = {
            'Name': account.name[:100],
            'AccountType': qb_type,
        }
        if account.code:
            data['AcctNum'] = account.code
        if account.note:
            data['Description'] = account.note[:4000]
        return data

    # ---- Pull (primary direction for accounts) ----

    def pull(self, client, config, job):
        if job.qb_entity_id:
            resp = client.read('Account', job.qb_entity_id)
            qb_data = resp.get('Account', {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = self._qb_account_to_odoo(qb_data)
        qb_id = vals['qb_account_id']

        existing = self.env['account.account'].search([
            ('qb_account_id', '=', qb_id),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            update_vals = {
                'name': vals.get('name', existing.name),
                'qb_sync_token': vals['qb_sync_token'],
                'qb_last_synced': vals['qb_last_synced'],
            }
            if vals.get('code') and vals['code'] != existing.code:
                update_vals['code'] = vals['code']
            if vals.get('note'):
                update_vals['note'] = vals['note']
            existing.with_context(skip_qb_sync=True).write(update_vals)
        else:
            vals['company_id'] = config.company_id.id
            self.env['account.account'].with_context(
                skip_qb_sync=True,
            ).create(vals)

        return {'qb_id': qb_id}

    def push(self, client, config, job):
        """Push an account to QBO (less common, but supported)."""
        account = self.env['account.account'].browse(job.odoo_record_id)
        if not account.exists():
            return {}

        payload = self._odoo_to_qb_account(account)

        if account.qb_account_id:
            existing = client.read('Account', account.qb_account_id)
            entity_data = existing.get('Account', {})
            payload['Id'] = account.qb_account_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Account', payload)
        else:
            resp = client.create('Account', payload)

        created = resp.get('Account', {})
        account.write({
            'qb_account_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        """Pull the full chart of accounts from QBO."""
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Account', where_clause=where)
        Account = self.env['account.account']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_account_to_odoo(qb_data)

            existing = Account.search([
                ('qb_account_id', '=', qb_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)

            if existing:
                update_vals = {
                    'name': vals.get('name', existing.name),
                    'qb_sync_token': vals['qb_sync_token'],
                    'qb_last_synced': vals['qb_last_synced'],
                }
                if vals.get('code') and vals['code'] != existing.code:
                    update_vals['code'] = vals['code']
                if vals.get('note'):
                    update_vals['note'] = vals['note']
                existing.with_context(skip_qb_sync=True).write(update_vals)
            else:
                vals['company_id'] = config.company_id.id
                Account.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        pass
