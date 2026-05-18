import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncPayments(models.AbstractModel):
    _name = 'qb.sync.payments'
    _description = 'QuickBooks Payment / BillPayment Sync'

    # ---- Field helpers ----

    @staticmethod
    def _payment_note_field(payment):
        """Return the name of the free-text note field on account.payment.

        Odoo 18 replaced ``account.payment.ref`` with ``memo``. Try the new
        name first, falling back to ``ref`` for older versions.
        """
        if 'memo' in payment._fields:
            return 'memo'
        if 'ref' in payment._fields:
            return 'ref'
        return None

    @classmethod
    def _payment_note(cls, payment):
        field_name = cls._payment_note_field(payment)
        if not field_name:
            return ''
        return getattr(payment, field_name, '') or ''

    # ---- Odoo → QBO ----

    def _odoo_payment_to_qb(self, payment):
        """Map Odoo account.payment to QBO Payment dict."""
        note = self._payment_note(payment)
        data = {
            'TotalAmt': abs(payment.amount),
            'TxnDate': (
                payment.date.isoformat() if payment.date else None
            ),
            'PrivateNote': note[:4000] if note else None,
        }

        if payment.partner_id and payment.partner_id.qb_customer_id:
            data['CustomerRef'] = {
                'value': payment.partner_id.qb_customer_id,
                'name': payment.partner_id.name,
            }

        if payment.currency_id:
            data['CurrencyRef'] = {'value': payment.currency_id.name}

        # Link to invoices if reconciled
        linked_invoices = self._get_linked_invoices(payment)
        if linked_invoices:
            lines = []
            for inv in linked_invoices:
                if inv.qb_invoice_id:
                    lines.append({
                        'Amount': abs(inv.amount_total),
                        'LinkedTxn': [{
                            'TxnId': inv.qb_invoice_id,
                            'TxnType': 'Invoice',
                        }],
                    })
            if lines:
                data['Line'] = lines

        return {k: v for k, v in data.items() if v is not None}

    def _odoo_billpayment_to_qb(self, payment):
        """Map Odoo vendor payment to QBO BillPayment dict."""
        note = self._payment_note(payment)
        data = {
            'TotalAmt': abs(payment.amount),
            'PayType': 'Check',
            'TxnDate': (
                payment.date.isoformat() if payment.date else None
            ),
            'PrivateNote': note[:4000] if note else None,
        }

        if payment.partner_id and payment.partner_id.qb_vendor_id:
            data['VendorRef'] = {
                'value': payment.partner_id.qb_vendor_id,
                'name': payment.partner_id.name,
            }

        # Bank account
        journal = payment.journal_id
        if journal and journal.default_account_id:
            acct = journal.default_account_id
            if acct.qb_account_id:
                data['CheckPayment'] = {
                    'BankAccountRef': {'value': acct.qb_account_id},
                }

        # Link to bills
        linked_bills = self._get_linked_bills(payment)
        if linked_bills:
            lines = []
            for bill in linked_bills:
                if bill.qb_bill_id:
                    lines.append({
                        'Amount': abs(bill.amount_total),
                        'LinkedTxn': [{
                            'TxnId': bill.qb_bill_id,
                            'TxnType': 'Bill',
                        }],
                    })
            if lines:
                data['Line'] = lines

        if payment.currency_id:
            data['CurrencyRef'] = {'value': payment.currency_id.name}

        return {k: v for k, v in data.items() if v is not None}

    def _get_linked_invoices(self, payment):
        """Find invoices linked to this customer payment via reconciliation."""
        invoices = getattr(payment, 'reconciled_invoice_ids', self.env['account.move'])
        if not invoices:
            return self.env['account.move']
        return invoices.filtered(
            lambda m: m.move_type == 'out_invoice',
        )

    def _get_linked_bills(self, payment):
        """Find bills linked to this vendor payment via reconciliation."""
        bills = getattr(payment, 'reconciled_bill_ids', self.env['account.move'])
        if not bills:
            return self.env['account.move']
        return bills.filtered(
            lambda m: m.move_type == 'in_invoice',
        )

    # ---- QBO → Odoo ----

    def _qb_payment_to_odoo(self, qb_data, config):
        """Map QBO Payment to Odoo account.payment vals."""
        vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'amount': qb_data.get('TotalAmt', 0.0),
            'qb_payment_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': config.company_id.id,
        }

        if qb_data.get('TxnDate'):
            vals['date'] = qb_data['TxnDate']

        customer_ref = qb_data.get('CustomerRef', {})
        if customer_ref.get('value'):
            partner = self.env['res.partner'].search([
                ('qb_customer_id', '=', customer_ref['value']),
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id

        vals.update(self.env['qb.currency.helper'].payment_currency_vals(qb_data, config))

        note_field = self._payment_note_field(self.env['account.payment'])
        if note_field and qb_data.get('PrivateNote'):
            vals[note_field] = qb_data['PrivateNote']

        self._apply_bank_journal(vals, qb_data, config, kind='customer')

        return vals

    def _qb_billpayment_to_odoo(self, qb_data, config):
        """Map QBO BillPayment to Odoo account.payment vals."""
        vals = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': qb_data.get('TotalAmt', 0.0),
            'qb_billpayment_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': config.company_id.id,
        }

        if qb_data.get('TxnDate'):
            vals['date'] = qb_data['TxnDate']

        vendor_ref = qb_data.get('VendorRef', {})
        if vendor_ref.get('value'):
            partner = self.env['res.partner'].search([
                ('qb_vendor_id', '=', vendor_ref['value']),
            ], limit=1)
            if partner:
                vals['partner_id'] = partner.id

        vals.update(self.env['qb.currency.helper'].payment_currency_vals(qb_data, config))

        note_field = self._payment_note_field(self.env['account.payment'])
        if note_field and qb_data.get('PrivateNote'):
            vals[note_field] = qb_data['PrivateNote']

        self._apply_bank_journal(vals, qb_data, config, kind='bill')

        return vals

    # ---- Bank journal resolution ----

    def _extract_qbo_bank_ref(self, qb_data, kind):
        """Return the QBO Account id referenced by a Payment / BillPayment payload.

        Customer Payment: ``DepositToAccountRef.value``.
        Vendor BillPayment: ``CheckPayment.BankAccountRef.value`` (Check pay type)
        or ``CreditCardPayment.CCAccountRef.value`` (Credit Card pay type).
        """
        if kind == 'customer':
            deposit = qb_data.get('DepositToAccountRef') or {}
            return (deposit.get('value') or '').strip()
        check = qb_data.get('CheckPayment') or {}
        bank_ref = (check.get('BankAccountRef') or {}).get('value')
        if bank_ref:
            return str(bank_ref).strip()
        cc = qb_data.get('CreditCardPayment') or {}
        cc_ref = (cc.get('CCAccountRef') or {}).get('value')
        if cc_ref:
            return str(cc_ref).strip()
        return ''

    def _resolve_bank_journal(self, qb_data, config, kind):
        """Resolve the Odoo bank/cash journal for a QBO payment payload.

        Returns the journal record or an empty recordset. Honors operator
        intent in two ways:
          - Journal pre-linked via ``account.journal.qb_account_id`` is
            adopted directly.
          - Otherwise, find the Odoo account by ``qb_account_id`` and pick
            the journal whose ``default_account_id`` points at it.
        """
        Journal = self.env['account.journal'].sudo()
        qbo_account_id = self._extract_qbo_bank_ref(qb_data, kind)
        if not qbo_account_id:
            return Journal.browse()
        company_domain = [('company_id', '=', config.company_id.id)]
        direct = Journal.search(
            company_domain + [('qb_account_id', '=', qbo_account_id)], limit=1,
        )
        if direct:
            return direct
        Account = self.env['account.account'].sudo()
        odoo_account = Account.search(
            [('qb_account_id', '=', qbo_account_id)], limit=1,
        )
        if not odoo_account:
            return Journal.browse()
        return Journal.search(
            company_domain + [('default_account_id', '=', odoo_account.id)],
            limit=1,
        )

    def _apply_bank_journal(self, vals, qb_data, config, kind):
        qbo_account_id = self._extract_qbo_bank_ref(qb_data, kind)
        if not qbo_account_id:
            return
        journal = self._resolve_bank_journal(qb_data, config, kind)
        if journal:
            vals['journal_id'] = journal.id
            return
        message = (
            'QBO %s payment %s references bank account id %s, but no Odoo '
            'journal is linked to it. Either set '
            'account.journal.qb_account_id on the matching Odoo bank '
            'journal, or run "Apply QBO Account Mapping" in Settings to '
            'link the underlying Odoo account.'
        ) % (kind, qb_data.get('Id') or '?', qbo_account_id)
        existing_err = vals.get('qb_sync_error')
        vals['qb_sync_error'] = (existing_err + ' | ' if existing_err else '') + message
        _logger.warning(message)

    # ---- Push ----

    def push(self, client, config, job):
        payment = self.env['account.payment'].browse(job.odoo_record_id)
        if not payment.exists():
            return {}

        is_customer = job.entity_type == 'payment'
        qb_name = 'Payment' if is_customer else 'BillPayment'
        qb_id_field = 'qb_payment_id' if is_customer else 'qb_billpayment_id'
        mapper = (
            self._odoo_payment_to_qb if is_customer
            else self._odoo_billpayment_to_qb
        )

        payload = mapper(payment)
        qb_id = getattr(payment, qb_id_field)

        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity_data = matcher.find_qbo_match(client, job.entity_type, payment)
            if entity_data:
                qb_id = str(entity_data.get('Id', ''))
                matcher.link_odoo_record(payment, job.entity_type, entity_data)

        if qb_id:
            existing = client.read(qb_name, qb_id)
            entity_data = existing.get(qb_name, {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update(qb_name, payload)
        else:
            resp = client.create(qb_name, payload)

        created = resp.get(qb_name, {})
        payment.with_context(skip_qb_sync=True).write({
            qb_id_field: str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    # ---- Pull ----

    def pull(self, client, config, job):
        is_customer = job.entity_type == 'payment'
        qb_name = 'Payment' if is_customer else 'BillPayment'
        qb_id_field = 'qb_payment_id' if is_customer else 'qb_billpayment_id'
        mapper = (
            self._qb_payment_to_odoo if is_customer
            else self._qb_billpayment_to_odoo
        )

        if job.qb_entity_id:
            resp = client.read(qb_name, job.qb_entity_id)
            qb_data = resp.get(qb_name, {})
        elif job.odoo_record_id:
            payment = self.env['account.payment'].browse(job.odoo_record_id)
            qb_id = getattr(payment, qb_id_field)
            if not qb_id:
                return {}
            resp = client.read(qb_name, qb_id)
            qb_data = resp.get(qb_name, {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = mapper(qb_data, config)
        qb_id = str(qb_data.get('Id', ''))

        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match(job.entity_type, qb_data, config.company_id)

        if existing:
            matcher.link_odoo_record(existing, job.entity_type, qb_data)
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, job.entity_type)
            if decision == 'qbo':
                existing.with_context(skip_qb_sync=True).write(vals)
            elif decision == 'conflict':
                job.write({'state': 'conflict'})
        else:
            self.env['account.payment'].with_context(
                skip_qb_sync=True,
            ).create(vals)

        return {'qb_id': qb_id}

    # ---- Bulk ----

    def pull_all(self, client, config, entity_type):
        is_customer = entity_type == 'payment'
        qb_name = 'Payment' if is_customer else 'BillPayment'
        qb_id_field = 'qb_payment_id' if is_customer else 'qb_billpayment_id'
        mapper = (
            self._qb_payment_to_odoo if is_customer
            else self._qb_billpayment_to_odoo
        )

        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all(qb_name, where_clause=where)
        Payment = self.env['account.payment']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = mapper(qb_data, config)

            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match(entity_type, qb_data, config.company_id)

            if existing:
                matcher.link_odoo_record(existing, entity_type, qb_data)
                resolver = self.env['qb.conflict.resolver']
                if resolver.resolve(config, existing, qb_data, entity_type) == 'qbo':
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Payment.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        is_customer = entity_type == 'payment'
        qb_id_field = 'qb_payment_id' if is_customer else 'qb_billpayment_id'
        partner_type_val = 'customer' if is_customer else 'supplier'

        payments = self.env['account.payment'].search([
            (qb_id_field, '=', False),
            ('qb_do_not_sync', '=', False),
            ('state', '=', 'posted'),
            ('partner_type', '=', partner_type_val),
            ('company_id', '=', config.company_id.id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for payment in payments:
            queue.enqueue(
                entity_type=entity_type,
                direction='push',
                operation='create',
                odoo_record_id=payment.id,
                odoo_model='account.payment',
                company=config.company_id,
            )
