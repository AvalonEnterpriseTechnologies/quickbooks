from odoo import api, fields, models


class QuickbooksAccountReconciliation(models.Model):
    _name = 'quickbooks.account.reconciliation'
    _description = 'QuickBooks Chart of Accounts Reconciliation'
    _order = 'last_seen desc, qb_name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True,
    )
    qb_account_id = fields.Char(required=True, index=True)
    qb_name = fields.Char(required=True)
    qb_code = fields.Char(index=True)
    qb_account_type = fields.Char()
    qb_account_subtype = fields.Char()
    account_id = fields.Many2one('account.account', index=True, ondelete='set null')
    account_code = fields.Char(related='account_id.code', store=True)
    account_type = fields.Selection(related='account_id.account_type', store=True)
    decision = fields.Selection(
        [
            ('linked_by_id', 'Linked by QuickBooks ID'),
            ('linked_by_code', 'Linked by Function + Code'),
            ('linked_by_name', 'Linked by Function + Name'),
            ('linked_by_compatible_code', 'Linked by Compatible Code'),
            ('linked_by_compatible_name', 'Linked by Compatible Name'),
            ('created', 'Created in Odoo'),
            ('conflict', 'Conflict'),
        ],
        required=True,
        index=True,
    )
    note = fields.Char()
    last_seen = fields.Datetime(default=fields.Datetime.now, required=True)

    _qb_account_company_uniq = models.Constraint(
        'unique(company_id, qb_account_id)',
        'A QuickBooks account can only have one reconciliation row per company.',
    )

    @api.model
    def record_decision(self, config, qb_data, account, decision):
        qb_id = str(qb_data.get('Id') or '')
        if not qb_id:
            return self.browse()
        vals = {
            'company_id': config.company_id.id,
            'qb_account_id': qb_id,
            'qb_name': qb_data.get('Name') or qb_id,
            'qb_code': qb_data.get('AcctNum') or '',
            'qb_account_type': qb_data.get('AccountType') or '',
            'qb_account_subtype': qb_data.get('AccountSubType') or '',
            'account_id': account.id if account else False,
            'decision': decision if decision in dict(self._fields['decision'].selection) else 'conflict',
            'note': self._decision_note(qb_data, account, decision),
            'last_seen': fields.Datetime.now(),
        }
        existing = self.search([
            ('company_id', '=', config.company_id.id),
            ('qb_account_id', '=', qb_id),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    @api.model
    def _decision_note(self, qb_data, account, decision):
        if not account:
            return 'No matching Odoo account was found.'
        if decision == 'created':
            return 'Created missing account from QuickBooks.'
        return 'Linked QuickBooks %s to Odoo %s.' % (
            qb_data.get('Name') or qb_data.get('Id'),
            account.display_name,
        )
