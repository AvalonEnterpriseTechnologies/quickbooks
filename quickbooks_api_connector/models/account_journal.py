from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    qb_journal_key = fields.Char(
        string='QuickBooks Journal Key',
        index=True,
        copy=False,
        help='Deterministic connector key used to keep generated journals idempotent.',
    )
    qb_account_id = fields.Char(
        string='QB Account ID',
        index=True,
        copy=False,
    )
