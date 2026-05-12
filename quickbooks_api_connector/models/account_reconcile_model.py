from odoo import fields, models


class AccountReconcileModel(models.Model):
    _inherit = 'account.reconcile.model'

    qb_bank_rule_id = fields.Char(string='QB Bank Rule ID', index=True, copy=False)
    qb_conditions_json = fields.Json(string='QB Conditions JSON', copy=False)
    qb_api_status = fields.Selection(
        [('manual', 'Manual Only - No Public QBO API')],
        string='QB API Status',
        default='manual',
        copy=False,
    )
