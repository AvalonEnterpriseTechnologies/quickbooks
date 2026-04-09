import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncJournalEntries(models.AbstractModel):
    _name = 'qb.sync.journal.entries'
    _description = 'QuickBooks Journal Entry Sync'

    # ---- Odoo → QBO ----

    def _odoo_je_to_qb(self, move):
        """Map Odoo journal entry to QBO JournalEntry."""
        lines = []
        for line in move.line_ids.filtered(lambda l: l.debit or l.credit):
            posting_type = 'Debit' if line.debit else 'Credit'
            amount = line.debit or line.credit

            je_line = {
                'DetailType': 'JournalEntryLineDetail',
                'Amount': abs(amount),
                'Description': (line.name or '')[:4000],
                'JournalEntryLineDetail': {
                    'PostingType': posting_type,
                },
            }

            if line.account_id and line.account_id.qb_account_id:
                je_line['JournalEntryLineDetail']['AccountRef'] = {
                    'value': line.account_id.qb_account_id,
                    'name': line.account_id.name,
                }

            if line.partner_id:
                entity = {}
                if line.partner_id.qb_customer_id:
                    entity = {
                        'value': line.partner_id.qb_customer_id,
                        'name': line.partner_id.name,
                        'type': 'Customer',
                    }
                elif line.partner_id.qb_vendor_id:
                    entity = {
                        'value': line.partner_id.qb_vendor_id,
                        'name': line.partner_id.name,
                        'type': 'Vendor',
                    }
                if entity:
                    je_line['JournalEntryLineDetail']['Entity'] = {
                        'EntityRef': entity,
                        'Type': entity.get('type', 'Customer'),
                    }

            lines.append(je_line)

        data = {
            'Line': lines,
            'TxnDate': move.date.isoformat() if move.date else None,
            'DocNumber': move.name or '',
            'PrivateNote': (move.narration or '')[:4000] or None,
        }

        if move.currency_id:
            data['CurrencyRef'] = {'value': move.currency_id.name}

        return {k: v for k, v in data.items() if v is not None}

    # ---- QBO → Odoo ----

    def _qb_je_to_odoo(self, qb_data, config):
        """Map QBO JournalEntry to Odoo account.move vals."""
        vals = {
            'move_type': 'entry',
            'qb_je_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': config.company_id.id,
        }

        if qb_data.get('TxnDate'):
            vals['date'] = qb_data['TxnDate']
        if qb_data.get('DocNumber'):
            vals['ref'] = qb_data['DocNumber']
        if qb_data.get('PrivateNote'):
            vals['narration'] = qb_data['PrivateNote']

        currency_ref = qb_data.get('CurrencyRef', {})
        if currency_ref.get('value'):
            currency = self.env['res.currency'].search([
                ('name', '=', currency_ref['value']),
            ], limit=1)
            if currency:
                vals['currency_id'] = currency.id

        # Journal entry lines
        move_lines = []
        for qb_line in qb_data.get('Line', []):
            if qb_line.get('DetailType') != 'JournalEntryLineDetail':
                continue
            detail = qb_line.get('JournalEntryLineDetail', {})
            posting_type = detail.get('PostingType', 'Debit')
            amount = qb_line.get('Amount', 0.0)

            line_vals = {
                'name': qb_line.get('Description', 'Journal Entry Line'),
                'debit': amount if posting_type == 'Debit' else 0.0,
                'credit': amount if posting_type == 'Credit' else 0.0,
            }

            account_ref = detail.get('AccountRef', {})
            if account_ref.get('value'):
                account = self.env['account.account'].search([
                    ('qb_account_id', '=', account_ref['value']),
                    ('company_id', '=', config.company_id.id),
                ], limit=1)
                if account:
                    line_vals['account_id'] = account.id

            entity = detail.get('Entity', {})
            entity_ref = entity.get('EntityRef', {})
            if entity_ref.get('value'):
                entity_type = entity.get('Type', 'Customer')
                if entity_type == 'Customer':
                    partner = self.env['res.partner'].search([
                        ('qb_customer_id', '=', entity_ref['value']),
                    ], limit=1)
                else:
                    partner = self.env['res.partner'].search([
                        ('qb_vendor_id', '=', entity_ref['value']),
                    ], limit=1)
                if partner:
                    line_vals['partner_id'] = partner.id

            move_lines.append((0, 0, line_vals))

        if move_lines:
            vals['line_ids'] = move_lines

        return vals

    # ---- Push ----

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists() or move.move_type != 'entry':
            return {}

        payload = self._odoo_je_to_qb(move)
        qb_id = move.qb_je_id

        if qb_id:
            existing = client.read('JournalEntry', qb_id)
            entity_data = existing.get('JournalEntry', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('JournalEntry', payload)
        else:
            resp = client.create('JournalEntry', payload)

        created = resp.get('JournalEntry', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_je_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    # ---- Pull ----

    def pull(self, client, config, job):
        if job.qb_entity_id:
            resp = client.read('JournalEntry', job.qb_entity_id)
            qb_data = resp.get('JournalEntry', {})
        elif job.odoo_record_id:
            move = self.env['account.move'].browse(job.odoo_record_id)
            if not move.qb_je_id:
                return {}
            resp = client.read('JournalEntry', move.qb_je_id)
            qb_data = resp.get('JournalEntry', {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = self._qb_je_to_odoo(qb_data, config)
        qb_id = str(qb_data.get('Id', ''))

        existing = self.env['account.move'].search([
            ('qb_je_id', '=', qb_id),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if existing:
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, 'journal_entry')
            if decision == 'qbo':
                line_vals = vals.pop('line_ids', [])
                existing.with_context(skip_qb_sync=True).write(vals)
                if line_vals and existing.state == 'draft':
                    existing.line_ids.filtered(
                        lambda l: l.display_type not in ('line_section', 'line_note'),
                    ).unlink()
                    existing.with_context(skip_qb_sync=True).write({
                        'line_ids': line_vals,
                    })
            elif decision == 'conflict':
                job.write({'state': 'conflict'})
        else:
            self.env['account.move'].with_context(skip_qb_sync=True).create(vals)

        return {'qb_id': qb_id}

    # ---- Bulk ----

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('JournalEntry', where_clause=where)
        Move = self.env['account.move']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_je_to_odoo(qb_data, config)

            existing = Move.search([
                ('qb_je_id', '=', qb_id),
                ('company_id', '=', config.company_id.id),
            ], limit=1)

            if existing:
                resolver = self.env['qb.conflict.resolver']
                if resolver.resolve(config, existing, qb_data, 'journal_entry') == 'qbo':
                    vals.pop('line_ids', None)
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Move.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        moves = self.env['account.move'].search([
            ('move_type', '=', 'entry'),
            ('qb_je_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('state', '=', 'posted'),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            queue.enqueue(
                entity_type='journal_entry',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )
