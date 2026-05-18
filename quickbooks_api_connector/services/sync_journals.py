import re

from odoo import api, models


class QBSyncJournals(models.AbstractModel):
    _name = 'qb.sync.journals'
    _description = 'QuickBooks Journal Sync'

    @api.model
    def ensure_journals_for_accounts(self, config):
        # Legacy "default" general journal kept as a safety fallback for JEs
        # whose dominant line we cannot resolve to a per-account journal.
        # Renamed from "QuickBooks Journal Entries" so it is no longer the
        # destination of every QBO JE — the per-account routing in
        # sync_journal_entries handles that now.
        self.ensure_general_journal(
            config, key='qbo:general:default',
            name='Migrated Adjustments (legacy fallback)',
        )
        # Opening-balances landing journal. Renamed from the legacy
        # "QuickBooks Opening Balances" to plain "Opening Balances" so the
        # journal list no longer reads as a QBO-only artifact.
        self.ensure_general_journal(
            config, key='qbo:general:opening',
            name='Opening Balances',
        )
        accounts = self._linked_financial_accounts(config)
        for account in accounts:
            journal_type = self._journal_type_for_account(account)
            if journal_type not in ('bank', 'cash'):
                continue
            self._ensure_account_journal(config, account, journal_type)

    @api.model
    def ensure_general_journal(self, config, key='qbo:general:default',
                               name='Migrated Adjustments (legacy fallback)'):
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search([
            ('company_id', '=', config.company_id.id),
            ('qb_journal_key', '=', key),
        ], limit=1)
        if journal:
            return journal
        return Journal.create({
            'name': name,
            'type': 'general',
            'code': self._available_journal_code('QBOG', config.company_id),
            'company_id': config.company_id.id,
            'qb_journal_key': key,
        })

    @api.model
    def ensure_general_journal_for_account(self, config, account):
        """Return a dedicated general journal for ``account``, creating it if needed.

        Used by sync_journal_entries to route each QBO JournalEntry into a
        per-account general journal (based on its dominant debit/credit
        line) instead of dumping everything into the legacy single
        "QuickBooks Journal Entries" bucket. The journal is keyed by
        qb_journal_key = 'qbo:general:account:<qb_account_id|odoo_id>',
        so the lookup is idempotent across re-syncs.
        """
        Journal = self.env['account.journal'].sudo()
        if not account:
            return self.ensure_general_journal(config)
        anchor = account.qb_account_id or str(account.id)
        key = 'qbo:general:account:%s' % anchor
        existing = Journal.search([
            ('company_id', '=', config.company_id.id),
            ('qb_journal_key', '=', key),
        ], limit=1)
        if existing:
            return existing

        code_seed = account.code or account.qb_account_code or anchor
        code_base = re.sub(r'[^A-Za-z0-9]', '', str(code_seed).upper())[:5] or 'JE'
        name_parts = []
        if account.code:
            name_parts.append(str(account.code))
        if account.name:
            name_parts.append(account.name)
        display_name = ' '.join(name_parts) or 'QuickBooks JE Bucket'
        journal_name = ('JE: %s' % display_name)[:64]

        return Journal.create({
            'name': journal_name,
            'type': 'general',
            'code': self._available_journal_code(code_base, config.company_id),
            'company_id': config.company_id.id,
            'qb_journal_key': key,
        })

    def _linked_financial_accounts(self, config):
        Account = self.env['account.account'].sudo()
        domain = [('qb_account_id', '!=', False)]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', config.company_id.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', '=', config.company_id.id))
        return Account.search(domain)

    def _ensure_account_journal(self, config, account, journal_type):
        """Locate, adopt, or create the Odoo journal that backs a QBO bank/cash account.

        Lookup order:
          1. Journal already tagged by the connector via qb_journal_key.
          2. Journal pre-linked by the operator via qb_account_id (the
             keep-existing-Odoo-journals path: the operator pastes the QBO
             account id onto BNK1/BNK2/etc. so the connector reuses them
             instead of seeding parallel QBO-derived journals).
          3. Journal whose default_account_id already equals the linked
             Odoo account (defensive adoption for environments where the
             operator linked via the account rather than the journal).
          4. Create a fresh journal.
        """
        Journal = self.env['account.journal'].sudo()
        company_domain = [('company_id', '=', config.company_id.id)]
        key = 'qbo:%s:%s' % (journal_type, account.qb_account_id)

        journal = Journal.search(
            company_domain + [('qb_journal_key', '=', key)], limit=1,
        )
        if not journal and account.qb_account_id:
            journal = Journal.search(
                company_domain + [('qb_account_id', '=', account.qb_account_id)],
                limit=1,
            )
        if not journal:
            journal = Journal.search(
                company_domain + [('default_account_id', '=', account.id)],
                limit=1,
            )

        if journal:
            write_vals = {
                'qb_journal_key': key,
                'qb_account_id': account.qb_account_id,
            }
            if not journal.default_account_id:
                write_vals['default_account_id'] = account.id
            journal.write(write_vals)
            return journal

        return Journal.create({
            'name': account.name,
            'type': journal_type,
            'code': self._journal_code(account, config.company_id),
            'company_id': config.company_id.id,
            'default_account_id': account.id,
            'qb_journal_key': key,
            'qb_account_id': account.qb_account_id,
        })

    def _journal_type_for_account(self, account):
        qb_type = account.qb_account_type or ''
        qb_subtype = account.qb_account_subtype or ''
        if qb_type == 'Bank':
            return 'cash' if qb_subtype == 'CashOnHand' else 'bank'
        if qb_type == 'Credit Card':
            return 'bank'
        if account.account_type == 'asset_cash':
            return 'bank'
        return 'general'

    def _journal_code(self, account, company):
        raw = account.qb_account_code or account.code or account.name or account.qb_account_id
        code = re.sub(r'[^A-Za-z0-9]', '', raw.upper())[:5] or 'QBO'
        return self._available_journal_code(code, company)

    def _available_journal_code(self, code, company):
        Journal = self.env['account.journal'].sudo()
        base = (code or 'QBO')[:5]
        candidate = base
        index = 2
        while Journal.search([
            ('company_id', '=', company.id),
            ('code', '=', candidate),
        ], limit=1):
            suffix = str(index)
            candidate = '%s%s' % (base[:5 - len(suffix)], suffix)
            index += 1
        return candidate
