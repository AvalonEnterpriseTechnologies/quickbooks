import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    qb_customer_id = fields.Char(
        string='QB Customer ID', index=True, copy=False, tracking=True,
    )
    qb_vendor_id = fields.Char(
        string='QB Vendor ID', index=True, copy=False, tracking=True,
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
        if not self.env.context.get('skip_qb_sync') and not vals.get('qb_do_not_sync'):
            qb_fields = {
                'name', 'email', 'phone', 'mobile', 'street', 'street2',
                'city', 'zip', 'state_id', 'country_id', 'vat',
                'customer_rank', 'supplier_rank', 'company_type',
            }
            if qb_fields & set(vals.keys()):
                for rec in self.filtered(lambda r: not r.qb_do_not_sync):
                    rec._trigger_qb_sync('update')
        return res

    def _trigger_qb_sync(self, operation):
        self.ensure_one()
        queue = self.env['quickbooks.sync.queue']
        if self.customer_rank and self.customer_rank > 0:
            queue.enqueue(
                entity_type='customer',
                direction='push',
                operation=operation,
                odoo_record_id=self.id,
                odoo_model='res.partner',
            )
        if self.supplier_rank and self.supplier_rank > 0:
            queue.enqueue(
                entity_type='vendor',
                direction='push',
                operation=operation,
                odoo_record_id=self.id,
                odoo_model='res.partner',
            )

    def action_sync_to_qb(self):
        for rec in self:
            rec._trigger_qb_sync('update')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': 'Partner sync queued.',
                'type': 'info',
                'sticky': False,
            },
        }
