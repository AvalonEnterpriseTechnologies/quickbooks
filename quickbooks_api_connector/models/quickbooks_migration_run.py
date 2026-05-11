from odoo import fields, models


class QuickbooksMigrationRun(models.Model):
    _name = 'quickbooks.migration.run'
    _description = 'QuickBooks Migration Run'
    _order = 'started_at desc'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    started_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user, required=True,
    )
    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    finished_at = fields.Datetime()
    mode = fields.Selection(
        [('dry_run', 'Dry Run'), ('live', 'Live')],
        default='live',
        required=True,
    )
    state = fields.Selection(
        [
            ('planning', 'Planning'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='planning',
        required=True,
    )
    step_ids = fields.One2many(
        'quickbooks.migration.run.step', 'run_id', string='Steps',
    )
    summary = fields.Text()


class QuickbooksMigrationRunStep(models.Model):
    _name = 'quickbooks.migration.run.step'
    _description = 'QuickBooks Migration Run Step'
    _order = 'sequence, id'

    run_id = fields.Many2one(
        'quickbooks.migration.run', required=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    entity_type = fields.Char(required=True, index=True)
    direction = fields.Selection(
        [('push', 'Odoo to QBO'), ('pull', 'QBO to Odoo')],
        required=True,
    )
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('queued', 'Queued'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
        ],
        default='pending',
        required=True,
    )
    expected_count = fields.Integer()
    actual_count = fields.Integer()
    error_message = fields.Text()
    idempotency_key = fields.Char(index=True)
