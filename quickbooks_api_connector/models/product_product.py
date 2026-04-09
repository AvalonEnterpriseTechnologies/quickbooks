import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    qb_item_id = fields.Char(
        string='QB Item ID', index=True, copy=False, tracking=True,
    )
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_sync_error = fields.Text(string='Last Sync Error', copy=False)
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_qb_sync'):
            for rec in records.filtered(lambda r: not r.qb_do_not_sync):
                rec._trigger_qb_sync('create')
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_qb_sync'):
            qb_fields = {
                'name', 'default_code', 'list_price', 'standard_price',
                'type', 'categ_id', 'description', 'active',
                'taxes_id', 'supplier_taxes_id',
            }
            if qb_fields & set(vals.keys()):
                for rec in self.filtered(lambda r: not r.qb_do_not_sync):
                    rec._trigger_qb_sync('update')
        return res

    def _trigger_qb_sync(self, operation):
        self.ensure_one()
        self.env['quickbooks.sync.queue'].enqueue(
            entity_type='product',
            direction='push',
            operation=operation,
            odoo_record_id=self.id,
            odoo_model='product.product',
        )

    def action_sync_to_qb(self):
        for rec in self:
            rec._trigger_qb_sync('update')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': 'Product sync queued.',
                'type': 'info',
                'sticky': False,
            },
        }
