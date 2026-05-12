from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qb_project_id = fields.Char(string='QB Project ID', index=True, copy=False)
    qb_customer_id = fields.Char(string='QB Parent Customer ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
