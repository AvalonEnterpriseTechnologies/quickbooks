import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncAccounts(models.AbstractModel):
    _name = 'qb.sync.accounts'
    _description = 'QuickBooks Account Sync'

    def _qb_account_to_odoo(self, qb_data):
        """Map a QBO Account to Odoo account.account vals."""
        classification = self.env['qb.account.classifier'].classify(qb_data)

        vals = {
            'name': qb_data.get('Name', ''),
            'code': qb_data.get('AcctNum') or str(qb_data.get('Id', '')),
            'account_type': classification['odoo_type'],
            'qb_account_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_account_type': classification['qbo_type'],
            'qb_account_subtype': classification['qbo_subtype'],
            'qb_account_code': qb_data.get('AcctNum') or '',
            'qb_opening_balance': qb_data.get('OpeningBalance') or 0.0,
            'qb_opening_balance_date': qb_data.get('OpeningBalanceDate') or False,
            'qb_current_balance': qb_data.get('CurrentBalance') or 0.0,
            'qb_current_balance_with_subaccounts': (
                qb_data.get('CurrentBalanceWithSubAccounts') or 0.0
            ),
        }

        if qb_data.get('Description'):
            vals['note'] = qb_data['Description']

        return self.env['qb.record.matcher'].apply_user_overrides(
            vals, qb_data, 'account', direction='pull',
        )

    def _odoo_to_qb_account(self, account):
        """Map Odoo account.account to QBO Account dict (primarily for ref)."""
        qb_type = self.env['qb.account.classifier'].qbo_type_for_odoo_type(
            account.account_type,
        )

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

        matcher = self.env['qb.record.matcher']
        existing, decision = matcher.find_odoo_match_for_account(
            qb_data, config.company_id, return_reason=True,
        )

        if existing:
            matcher.link_odoo_record(existing, 'account', qb_data)
            update_vals = self._existing_account_update_vals(existing, vals, config)
            existing.with_context(skip_qb_sync=True).write(update_vals)
        else:
            vals = self._prepare_new_account_vals(vals, config.company_id)
            existing = self.env['account.account'].with_context(
                skip_qb_sync=True,
            ).create(vals)
            decision = 'created'

        self._log_reconciliation(config, qb_data, existing, decision)
        self.env['qb.sync.journals'].ensure_journals_for_accounts(config)

        return {'qb_id': qb_id}

    def push(self, client, config, job):
        """Push an account to QBO (less common, but supported)."""
        account = self.env['account.account'].browse(job.odoo_record_id)
        if not account.exists():
            return {}

        payload = self._odoo_to_qb_account(account)
        qb_id = account.qb_account_id

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity_data = matcher.find_qbo_match(client, 'account', account)
            if entity_data:
                qb_id = str(entity_data.get('Id', ''))
                matcher.link_odoo_record(account, 'account', entity_data)

        if qb_id:
            existing = client.read('Account', qb_id)
            entity_data = existing.get('Account', {})
            payload['Id'] = qb_id
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
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Account', where_clause=where)
        Account = self.env['account.account']
        matcher = self.env['qb.record.matcher']

        for qb_data in records:
            vals = self._qb_account_to_odoo(qb_data)

            existing, decision = matcher.find_odoo_match_for_account(
                qb_data, config.company_id, return_reason=True,
            )

            if existing:
                matcher.link_odoo_record(existing, 'account', qb_data)
                update_vals = self._existing_account_update_vals(existing, vals, config)
                existing.with_context(skip_qb_sync=True).write(update_vals)
            else:
                vals = self._prepare_new_account_vals(vals, config.company_id)
                existing = Account.with_context(skip_qb_sync=True).create(vals)
                decision = 'created'
            self._log_reconciliation(config, qb_data, existing, decision)

        self.env['qb.sync.journals'].ensure_journals_for_accounts(config)

    def push_all(self, client, config, entity_type):
        accounts = self.env['account.account'].search([
            ('company_id', '=', config.company_id.id),
            ('qb_account_id', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for account in accounts:
            queue.enqueue(
                entity_type='account',
                direction='push',
                operation='create',
                odoo_record_id=account.id,
                odoo_model='account.account',
                company=config.company_id,
            )

    def _existing_account_update_vals(self, account, vals, config):
        update_vals = {
            'qb_sync_token': vals['qb_sync_token'],
            'qb_last_synced': vals['qb_last_synced'],
            'qb_account_type': vals.get('qb_account_type'),
            'qb_account_subtype': vals.get('qb_account_subtype'),
            'qb_account_code': vals.get('qb_account_code'),
            'qb_opening_balance': vals['qb_opening_balance'],
            'qb_opening_balance_date': vals['qb_opening_balance_date'],
            'qb_current_balance': vals['qb_current_balance'],
            'qb_current_balance_with_subaccounts': (
                vals['qb_current_balance_with_subaccounts']
            ),
        }
        name = vals.get('name')
        if name and self._should_update_account_name(account, name, config):
            update_vals['name'] = name
        if vals.get('code') and not account.code:
            update_vals['code'] = vals['code']
        if (
            vals.get('account_type')
            and account.account_type == 'asset_current'
            and vals['account_type'] != 'asset_current'
        ):
            update_vals['account_type'] = vals['account_type']
        if vals.get('note') and not getattr(account, 'note', False):
            update_vals['note'] = vals['note']
        return {
            key: value for key, value in update_vals.items()
            if key in account._fields
        }

    def _prepare_new_account_vals(self, vals, company):
        Account = self.env['account.account']
        vals = dict(vals)
        if 'company_id' in Account._fields:
            vals['company_id'] = company.id
        elif 'company_ids' in Account._fields:
            vals['company_ids'] = [(4, company.id)]
        vals['code'] = self._available_account_code(vals.get('code'), company)
        return vals

    def _available_account_code(self, code, company):
        if not code:
            return code
        Account = self.env['account.account']
        base_domain = [('code', '=', code)]
        if 'company_ids' in Account._fields:
            base_domain.append(('company_ids', 'in', company.id))
        elif 'company_id' in Account._fields:
            base_domain.append(('company_id', 'in', [company.id, False]))
        if not Account.search(base_domain, limit=1):
            return code
        company_domain = [
            term for term in base_domain
            if not isinstance(term, tuple) or term[0] != 'code'
        ]
        suffix_code = '%s-QB' % code
        if not Account.search(company_domain + [('code', '=', suffix_code)], limit=1):
            return suffix_code
        index = 2
        while True:
            candidate = '%s-QB%s' % (code, index)
            if not Account.search(company_domain + [('code', '=', candidate)], limit=1):
                return candidate
            index += 1

    def _should_update_account_name(self, account, qb_name, config):
        strategy = getattr(config, 'account_name_strategy', 'keep_odoo') or 'keep_odoo'
        if strategy == 'mirror_qbo':
            return account.name != qb_name
        if strategy == 'prefer_qbo':
            current = (account.name or '').strip().casefold()
            return not current or current in ('account', 'bank', 'cash')
        return False

    def _log_reconciliation(self, config, qb_data, account, decision):
        self.env['quickbooks.account.reconciliation'].sudo().record_decision(
            config=config,
            qb_data=qb_data,
            account=account,
            decision=decision,
        )
