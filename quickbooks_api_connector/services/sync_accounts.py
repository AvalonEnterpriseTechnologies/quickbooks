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
            'qb_parent_account_id': (
                (qb_data.get('ParentRef') or {}).get('value') or ''
            ),
            'qb_is_subaccount': bool(qb_data.get('SubAccount')),
            'qb_fqn': qb_data.get('FullyQualifiedName') or '',
            'qb_opening_balance_date': qb_data.get('OpeningBalanceDate') or False,
            'qb_current_balance': qb_data.get('CurrentBalance') or 0.0,
            'qb_current_balance_with_subaccounts': (
                qb_data.get('CurrentBalanceWithSubAccounts') or 0.0
            ),
        }
        if qb_data.get('OpeningBalance') not in (None, '', 0, 0.0, '0', '0.0', '0.00'):
            vals['qb_opening_balance'] = qb_data.get('OpeningBalance')
        if qb_data.get('Active') is not None:
            vals['active'] = bool(qb_data.get('Active'))

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
        elif self._account_strategy(config) == 'map_only':
            self._log_unmapped_account(config, qb_data, qb_id)
            return {'qb_id': qb_id, 'unmapped': True}
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
        # The Chart of Accounts is foundational for nearly every downstream
        # entity (products, invoices, bills, journals, payments). Pull the
        # complete active + inactive list every time instead of using
        # config.last_sync_date; otherwise an existing connected config can
        # skip unchanged accounts and leave the database without required
        # account.account rows.
        records = client.query_all('Account', where_clause='Active IN (true, false)')
        Account = self.env['account.account']
        matcher = self.env['qb.record.matcher']
        strategy = self._account_strategy(config)
        stats = {
            'matched': 0, 'created': 0, 'updated': 0, 'failed': 0, 'unmapped': 0,
        }
        unmapped_rows = []

        for qb_data in records:
            qb_id = str(qb_data.get('Id') or '')
            try:
                vals = self._qb_account_to_odoo(qb_data)

                existing, decision = matcher.find_odoo_match_for_account(
                    qb_data, config.company_id, return_reason=True,
                )

                if existing:
                    stats['matched'] += 1
                    matcher.link_odoo_record(existing, 'account', qb_data)
                    update_vals = self._existing_account_update_vals(existing, vals, config)
                    if update_vals:
                        existing.with_context(skip_qb_sync=True).write(update_vals)
                        stats['updated'] += 1
                    self._log_reconciliation(config, qb_data, existing, decision)
                elif strategy == 'map_only':
                    stats['unmapped'] += 1
                    self._log_unmapped_account(config, qb_data, qb_id)
                    unmapped_rows.append(qb_data)
                else:
                    vals = self._prepare_new_account_vals(vals, config.company_id)
                    existing = Account.with_context(skip_qb_sync=True).create(vals)
                    decision = 'created'
                    stats['created'] += 1
                    self._log_reconciliation(config, qb_data, existing, decision)
            except Exception as exc:
                stats['failed'] += 1
                _logger.exception(
                    'Failed to pull QBO account %s (%s)',
                    qb_id, qb_data.get('Name'),
                )
                self.env['quickbooks.sync.log'].log_sync(
                    company_id=config.company_id.id,
                    entity_type='account',
                    direction='pull',
                    operation='update',
                    qb_entity_id=qb_id,
                    state='error',
                    error_message='%s: %s' % (qb_data.get('Name') or qb_id, exc),
                )

        self.env['qb.sync.journals'].ensure_journals_for_accounts(config)
        try:
            config.sudo().write({
                'qb_account_last_discovery': fields.Datetime.now(),
                'qb_account_discovered_count': len(records),
                'qb_account_mapped_count': stats['matched'],
                'qb_account_unmapped_count': stats['unmapped'],
            })
        except Exception:
            _logger.warning(
                'Could not write CoA discovery counters on quickbooks.config %s',
                config.id,
            )
        if unmapped_rows:
            self._raise_unmapped_account_activity(config, unmapped_rows)
        _logger.info(
            'CoA pull (%s): total=%d, matched=%d, created=%d, updated=%d, '
            'unmapped=%d, failed=%d',
            strategy, len(records), stats['matched'], stats['created'],
            stats['updated'], stats['unmapped'], stats['failed'],
        )

    def push_all(self, client, config, entity_type):
        Account = self.env['account.account']
        domain = [('qb_account_id', '=', False)]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', config.company_id.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', 'in', [config.company_id.id, False]))
        accounts = Account.search(domain)
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
            'qb_parent_account_id': vals.get('qb_parent_account_id'),
            'qb_is_subaccount': vals.get('qb_is_subaccount'),
            'qb_fqn': vals.get('qb_fqn'),
            'qb_opening_balance_date': vals['qb_opening_balance_date'],
            'qb_current_balance': vals['qb_current_balance'],
            'qb_current_balance_with_subaccounts': (
                vals['qb_current_balance_with_subaccounts']
            ),
        }
        if 'qb_opening_balance' in vals:
            update_vals['qb_opening_balance'] = vals['qb_opening_balance']
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
        if 'company_ids' in Account._fields:
            vals['company_ids'] = [(4, company.id)]
            vals.pop('company_id', None)
        elif 'company_id' in Account._fields:
            vals['company_id'] = company.id
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
        if account and hasattr(account, '_record_qb_link_decision'):
            account.sudo()._record_qb_link_decision(config, qb_data, decision)

    @staticmethod
    def _account_strategy(config):
        return getattr(config, 'account_strategy', 'map_only') or 'map_only'

    def _log_unmapped_account(self, config, qb_data, qb_id):
        qb_name = qb_data.get('Name') or ''
        qb_code = (qb_data.get('AcctNum') or '').strip() or '(no code)'
        qb_type = qb_data.get('AccountType') or ''
        message = (
            'QBO account %s [%s] %s of type "%s" has no matching Odoo '
            'account. Strategy=map_only, so no Odoo account was created. '
            'Map it manually: open the matching Odoo account, set "QB '
            'Account ID" to %s, and save. Then re-run the sync.'
        ) % (qb_code, qb_id, qb_name, qb_type, qb_id)
        self.env['quickbooks.sync.log'].log_sync(
            company_id=config.company_id.id,
            entity_type='account',
            direction='pull',
            operation='read',
            qb_entity_id=qb_id,
            state='warning',
            error_message=message,
        )

    def _raise_unmapped_account_activity(self, config, unmapped_rows):
        manager_group = self.env.ref(
            'quickbooks_api_connector.group_qb_manager',
            raise_if_not_found=False,
        )
        responsible = self.env.user
        if manager_group:
            # Odoo 19 dropped res.groups.users; fall back through user_ids /
            # all_user_ids / explicit search so the helper stays portable.
            members = None
            for field in ('user_ids', 'users', 'all_user_ids'):
                if field in manager_group._fields:
                    members = manager_group[field]
                    break
            if members is None:
                members = self.env['res.users'].sudo().search([
                    ('groups_id', 'in', manager_group.id),
                ])
            users = members.filtered(lambda u: u.active)
            if users:
                responsible = users[0]
        summary = (
            '%d QuickBooks accounts could not be mapped (strategy=map_only)'
        ) % len(unmapped_rows)
        sample = ', '.join(
            '%s %s' % (
                (row.get('AcctNum') or '').strip() or '(no code)',
                row.get('Name') or '',
            )
            for row in unmapped_rows[:5]
        )
        if len(unmapped_rows) > 5:
            sample += ' (+%d more)' % (len(unmapped_rows) - 5)
        note = (
            'The last QBO chart of accounts pull skipped %d account(s) '
            'because no matching Odoo account exists. Sample: %s. See the '
            'connector sync log entries with state=warning for the full '
            'list, then map each one by pasting its QBO ID onto the '
            'corresponding Odoo account.'
        ) % (len(unmapped_rows), sample)
        try:
            config.activity_schedule(
                'mail.mail_activity_data_warning',
                summary=summary,
                note=note,
                user_id=responsible.id,
            )
        except Exception:
            _logger.warning(
                'Could not raise unmapped-account activity on quickbooks.config %s',
                config.id,
            )
