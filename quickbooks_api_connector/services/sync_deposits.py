import logging

from odoo import api, fields, models

from .qb_api_client import QBApiError

_logger = logging.getLogger(__name__)

DEPOSIT_DESTINATION_ACCOUNT_TYPES = (
    'asset_cash',
    'liability_credit_card',
)

# Journal entries already represented elsewhere in QBO must not be re-pushed
# as deposits. These are the per-move QBO link fields populated when the entry
# was synced as another entity type.
EXCLUDED_QB_LINK_FIELDS = (
    'qb_invoice_id',
    'qb_bill_id',
    'qb_creditmemo_id',
    'qb_je_id',
    'qb_salesreceipt_id',
    'qb_transfer_id',
    'qb_refundreceipt_id',
    'qb_vendorcredit_id',
)


class QBSyncDeposits(models.AbstractModel):
    _name = 'qb.sync.deposits'
    _description = 'QuickBooks Deposit Sync'

    def _qb_deposit_to_odoo(self, qb_data, config):
        vals = {
            'qb_deposit_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }
        vals.update(self.env['qb.currency.helper'].currency_vals(qb_data, config))
        return vals

    def push(self, client, config, job):
        move = self.env['account.move'].browse(job.odoo_record_id)
        if not move.exists():
            return {}

        if not self._is_deposit_eligible_move(move):
            _logger.info(
                'Skipping move %s (id=%s) as QBO Deposit; already represented '
                'in QBO as another entity or not a deposit-shaped journal entry.',
                move.display_name, move.id,
            )
            return {'skipped': True}

        payload = self._odoo_to_qb_deposit(move)
        if not self._is_valid_deposit_payload(payload):
            _logger.info(
                'Skipping move %s (id=%s) as QBO Deposit; missing DepositToAccountRef '
                'or DepositLineDetail source lines.',
                move.display_name, move.id,
            )
            return {'skipped': True}

        qb_id = move.qb_deposit_id
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'deposit', move)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(move, 'deposit', entity)
        try:
            if qb_id:
                existing = client.read('Deposit', qb_id)
                entity = existing.get('Deposit', {})
                payload['Id'] = qb_id
                payload['SyncToken'] = entity.get('SyncToken', '0')
                payload['sparse'] = True
                resp = client.update('Deposit', payload)
            else:
                resp = client.create('Deposit', payload)
        except QBApiError as exc:
            _logger.error(
                'QBO Deposit push rejected for move %s (id=%s, qb_id=%s); '
                'payload=%s; error=%s',
                move.display_name, move.id, qb_id or '-', payload, exc,
            )
            raise

        created = resp.get('Deposit', {})
        move.with_context(skip_qb_sync=True).write({
            'qb_deposit_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def _odoo_to_qb_deposit(self, move):
        """Build a valid QBO Deposit payload from an Odoo journal entry.

        QBO requires a top-level DepositToAccountRef and every line must include
        DepositLineDetail. Treat the liquidity debit line as the destination
        account and credit lines as the deposited sources.
        """
        deposit_line = self._deposit_destination_line(move)
        if not deposit_line:
            return {}
        deposit_qb_id = self._normalized_qb_account_id(deposit_line.account_id)
        if not deposit_qb_id:
            return {}

        destination_account_id = deposit_line.account_id.id
        lines = []
        for line in move.line_ids.filtered(lambda l: l.credit > 0):
            # A credit on the same account as the destination is a transfer
            # leg, not a deposit source.
            if line.account_id.id == destination_account_id:
                continue
            if not line.credit or line.credit <= 0:
                continue
            qb_account_id = self._normalized_qb_account_id(line.account_id)
            if not qb_account_id:
                continue
            lines.append({
                'DetailType': 'DepositLineDetail',
                'Amount': line.credit,
                'Description': (line.name or move.ref or move.name or '')[:4000],
                'DepositLineDetail': {
                    'AccountRef': {'value': qb_account_id},
                },
            })
        if not lines:
            return {}

        payload = {
            'DepositToAccountRef': {'value': deposit_qb_id},
            'Line': lines,
        }
        if move.date:
            payload['TxnDate'] = move.date.isoformat()
        if move.ref:
            payload['PrivateNote'] = move.ref[:4000]
        return payload

    def _is_valid_deposit_payload(self, payload):
        if not payload:
            return False
        destination = payload.get('DepositToAccountRef') or {}
        if not destination.get('value'):
            return False
        lines = payload.get('Line') or []
        if not lines:
            return False
        for line in lines:
            detail = line.get('DepositLineDetail') or {}
            account_ref = detail.get('AccountRef') or {}
            if line.get('DetailType') != 'DepositLineDetail':
                return False
            if not account_ref.get('value'):
                return False
        return True

    def _deposit_destination_line(self, move):
        for line in move.line_ids.filtered(lambda l: l.debit > 0):
            account = line.account_id
            if not self._normalized_qb_account_id(account):
                continue
            if getattr(account, 'account_type', '') in DEPOSIT_DESTINATION_ACCOUNT_TYPES:
                return line
        return False

    @staticmethod
    def _normalized_qb_account_id(account):
        raw = getattr(account, 'qb_account_id', '') or ''
        return str(raw).strip()

    def _is_deposit_eligible_move(self, move):
        """Return True only for journal entries that can become a QBO Deposit.

        Excludes entries QBO already represents through another entity
        (Invoice, Bill, JournalEntry, SalesReceipt, etc.), payment-generated
        counter moves, bank statement reconciliations, and tax cash-basis
        mirror entries. Without these guards the queue could try to push the
        same business event twice as different QBO objects.
        """
        if move.move_type != 'entry':
            return False
        if move.state != 'posted':
            return False
        for fname in EXCLUDED_QB_LINK_FIELDS:
            if fname in move._fields and move[fname]:
                return False
        if 'origin_payment_id' in move._fields and move.origin_payment_id:
            return False
        if 'statement_line_id' in move._fields and move.statement_line_id:
            return False
        if (
            'tax_cash_basis_origin_move_id' in move._fields
            and move.tax_cash_basis_origin_move_id
        ):
            return False
        return True

    def _is_deposit_candidate(self, move):
        if not self._is_deposit_eligible_move(move):
            return False
        return self._is_valid_deposit_payload(self._odoo_to_qb_deposit(move))

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Deposit', qb_id)
        qb_data = resp.get('Deposit', {})
        if not qb_data:
            return {}
        vals = self._qb_deposit_to_odoo(qb_data, config)
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('deposit', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'deposit', qb_data)
            existing.with_context(skip_qb_sync=True).write(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Deposit', where_clause=where)
        Move = self.env['account.move']
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_deposit_to_odoo(qb_data, config)
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('deposit', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'deposit', qb_data)
                existing.with_context(skip_qb_sync=True).write(vals)

    def push_all(self, client, config, entity_type):
        moves = self.env['account.move'].search([
            ('move_type', '=', 'entry'),
            ('state', '=', 'posted'),
            ('qb_deposit_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for move in moves:
            if not self._is_deposit_candidate(move):
                self._cancel_pending_deposit_jobs(move)
                continue
            queue.enqueue(
                entity_type='deposit',
                direction='push',
                operation='create',
                odoo_record_id=move.id,
                odoo_model='account.move',
                company=config.company_id,
            )

    def _cancel_pending_deposit_jobs(self, move):
        jobs = self.env['quickbooks.sync.queue'].search([
            ('entity_type', '=', 'deposit'),
            ('direction', '=', 'push'),
            ('odoo_model', '=', 'account.move'),
            ('odoo_record_id', '=', move.id),
            ('state', 'in', ('pending', 'processing', 'conflict')),
        ])
        if jobs:
            jobs.write({
                'state': 'done',
                'error_message': (
                    'Skipped: this journal entry does not have the QBO account '
                    'mapping required to build a valid Deposit payload.'
                ),
            })
