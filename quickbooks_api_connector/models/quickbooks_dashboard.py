from datetime import timedelta

from odoo import fields, models


class QuickbooksDashboard(models.TransientModel):
    _name = 'quickbooks.dashboard'
    _description = 'QuickBooks Sync Dashboard'

    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True,
    )
    queue_depth = fields.Integer(compute='_compute_metrics')
    failed_queue_count = fields.Integer(compute='_compute_metrics')
    sync_errors_24h = fields.Integer(compute='_compute_metrics')
    sync_success_24h = fields.Integer(compute='_compute_metrics')
    last_successful_sync = fields.Datetime(compute='_compute_metrics')

    def _compute_metrics(self):
        Queue = self.env['quickbooks.sync.queue']
        Log = self.env['quickbooks.sync.log']
        since = fields.Datetime.now() - timedelta(days=1)
        for rec in self:
            domain = [('company_id', '=', rec.company_id.id)]
            rec.queue_depth = Queue.search_count(domain + [('state', 'in', ('pending', 'processing'))])
            rec.failed_queue_count = Queue.search_count(domain + [('state', '=', 'failed')])
            rec.sync_errors_24h = Log.search_count(domain + [
                ('state', '=', 'error'),
                ('create_date', '>=', since),
            ])
            rec.sync_success_24h = Log.search_count(domain + [
                ('state', '=', 'success'),
                ('create_date', '>=', since),
            ])
            last = Log.search(domain + [('state', '=', 'success')], limit=1)
            rec.last_successful_sync = last.create_date if last else False
