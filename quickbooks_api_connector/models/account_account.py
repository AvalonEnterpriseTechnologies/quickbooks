from odoo import api, fields, models


class AccountAccount(models.Model):
    _inherit = ['account.account', 'mail.thread']

    qb_account_id = fields.Char(
        string='QB Account ID', index=True, copy=False,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_opening_balance = fields.Monetary(
        string='QB Opening Balance',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_opening_balance_date = fields.Date(
        string='QB Opening Balance Date',
        copy=False,
    )
    qb_current_balance = fields.Monetary(
        string='QB Current Balance',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_current_balance_with_subaccounts = fields.Monetary(
        string='QB Current Balance With Subaccounts',
        currency_field='company_currency_id',
        copy=False,
    )
    qb_tb_balance = fields.Monetary(
        string='QB Trial Balance (Latest)',
        currency_field='company_currency_id',
        compute='_compute_qb_tb_balance',
    )
    qb_account_type = fields.Char(string='QB Account Type', copy=False)
    qb_account_subtype = fields.Char(string='QB Account Subtype', copy=False)
    qb_account_code = fields.Char(string='QB Account Number', copy=False)
    qb_parent_account_id = fields.Char(string='QB Parent Account ID', copy=False)
    qb_is_subaccount = fields.Boolean(string='QB Sub-account', copy=False)
    qb_fqn = fields.Char(string='QB Fully Qualified Name', copy=False)
    qb_link_decision = fields.Selection(
        [
            ('linked_by_id', 'Linked by QuickBooks ID'),
            ('linked_by_code', 'Linked by Function + Code'),
            ('linked_by_name', 'Linked by Function + Name'),
            ('linked_by_compatible_code', 'Linked by Compatible Code'),
            ('linked_by_compatible_name', 'Linked by Compatible Name'),
            ('created', 'Created in Odoo'),
            ('conflict', 'Conflict'),
        ],
        string='QB Link Decision',
        copy=False,
        tracking=True,
    )

    @api.depends('qb_account_id')
    def _compute_qb_tb_balance(self):
        for account in self:
            account.qb_tb_balance = account.qb_current_balance or 0.0

    def action_view_qbo_balances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Balance Variances',
            'res_model': 'qb.balance.variance',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {
                'default_account_id': self.id,
                'default_label': self.display_name,
            },
        }

    def action_view_qbo_subaccounts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Sub-accounts',
            'res_model': 'account.account',
            'view_mode': 'list,form',
            'domain': [('qb_parent_account_id', '=', self.qb_account_id)],
        }

    def _record_qb_link_decision(self, config, qb_data, decision):
        valid = dict(self._fields['qb_link_decision'].selection)
        decision = decision if decision in valid else 'conflict'
        note = self._qb_link_decision_note(qb_data, decision)
        self.write({'qb_link_decision': decision})
        self.message_post(
            body=note,
            subject='QuickBooks account reconciliation',
            subtype_xmlid='mail.mt_note',
        )
        return self

    def _qb_link_decision_note(self, qb_data, decision):
        self.ensure_one()
        if decision == 'created':
            return 'Created missing Odoo account from QuickBooks account %s.' % (
                qb_data.get('Name') or qb_data.get('Id') or '',
            )
        return 'Linked QuickBooks account %s to Odoo account %s using decision %s.' % (
            qb_data.get('Name') or qb_data.get('Id') or '',
            self.display_name,
            decision,
        )
