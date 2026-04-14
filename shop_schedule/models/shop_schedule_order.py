from odoo import api, fields, models


class ShopScheduleOrder(models.Model):
    _name = 'shop.schedule.order'
    _description = 'Shop Schedule Work Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'
    _rec_name = 'name'

    # ── Identity / ProShop link ─────────────────────────────────────
    name = fields.Char(
        string='WO #',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    proshop_wo_number = fields.Char(
        string='ProShop WO #',
        index=True,
        tracking=True,
        help='Work order number from ProShop ERP, e.g. 26-0032',
    )
    lead_id = fields.Many2one(
        'crm.lead',
        string='CRM Job',
        tracking=True,
        help='Linked CRM opportunity / job',
    )
    wo_type = fields.Selection(
        [
            ('repeat', 'Repeat Production'),
            ('first_article', 'First Article'),
            ('prototype', 'Prototype'),
            ('rework', 'Rework'),
            ('other', 'Other'),
        ],
        string='WO Type',
        tracking=True,
    )
    wo_class = fields.Char(string='WO Class')
    active = fields.Boolean(default=True)

    # ── Customer / partner ──────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        tracking=True,
    )
    customer_po = fields.Char(string='Customer PO #')

    # ── Part info ───────────────────────────────────────────────────
    part_number = fields.Char(string='Part #', tracking=True)
    part_rev = fields.Char(string='Part Rev')
    part_name = fields.Char(string='Part Name')
    part_description = fields.Text(string='Part Description')

    # ── Drawing ─────────────────────────────────────────────────────
    drawing_number = fields.Char(string='Drawing #')
    drawing_rev = fields.Char(string='Drawing Rev')

    # ── Material / stock ────────────────────────────────────────────
    qty_ordered = fields.Float(string='Qty Ordered')
    raw_stock_qty = fields.Float(string='Raw Stock Qty')
    material = fields.Char(string='Material', help='e.g. Steel A36 2.5 x 8 x 11')

    # ── Scheduling / dates ──────────────────────────────────────────
    stage_id = fields.Many2one(
        'shop.schedule.stage',
        string='Stage',
        tracking=True,
        group_expand='_group_expand_stage_ids',
        index=True,
        copy=True,
    )
    stage_category_id = fields.Many2one(
        related='stage_id.category_id',
        string='Stage Category',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(default=10, help='Order within a Kanban column')
    date_must_leave = fields.Date(string='Must Leave By', tracking=True)
    date_deadline = fields.Date(string='Customer Due', tracking=True)
    days_to_ship = fields.Integer(string='Days to Ship')
    delivery_priority = fields.Selection(
        [
            ('normal', 'Normal'),
            ('high', 'High'),
            ('urgent', 'Urgent'),
        ],
        string='Delivery Priority',
        default='normal',
    )

    # ── Financial ───────────────────────────────────────────────────
    labor_rate = fields.Float(string='Labor Rate')
    est_amount = fields.Float(string='Est $ Amount')
    per_part_fmv = fields.Float(string='Per Part FMV')

    # ── Project / planning ──────────────────────────────────────────
    project_code = fields.Char(string='Project Code')
    project_manager_id = fields.Many2one('res.users', string='Project Manager')
    planner_id = fields.Many2one('res.users', string='Planner')
    user_id = fields.Many2one('res.users', string='Operator', tracking=True)

    # ── Boolean flags ───────────────────────────────────────────────
    build_to_inventory = fields.Boolean(string='Build to Inventory')
    first_article_required = fields.Boolean(string='First Article Required')
    itar_controlled = fields.Boolean(string='ITAR Controlled')
    is_serialized = fields.Boolean(string='Is Serialized')
    count_as_ontime = fields.Boolean(string='Count as On-Time')
    taken_at_loss = fields.Boolean(string='Taken at Loss')

    # ── Kanban / UX ─────────────────────────────────────────────────
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Low'), ('2', 'High'), ('3', 'Urgent')],
        default='0',
    )
    kanban_state = fields.Selection(
        [
            ('normal', 'In Progress'),
            ('done', 'Ready'),
            ('blocked', 'Blocked'),
        ],
        string='Kanban State',
        default='normal',
        tracking=True,
    )
    color = fields.Integer()
    tag_ids = fields.Many2many('shop.schedule.tag', string='Tags')

    # ── Operations / outside processing ─────────────────────────────
    operation_ids = fields.One2many(
        'shop.schedule.operation',
        'order_id',
        string='Operations',
    )
    outside_processing = fields.Char(
        string='Outside Processing',
        help='e.g. Paint (BUMP\'S AUTO BODY)',
    )

    # ── Notes / misc ────────────────────────────────────────────────
    notes = fields.Html(string='Notes')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    # ── Computed ────────────────────────────────────────────────────
    operation_count = fields.Integer(compute='_compute_operation_count')

    @api.depends('operation_ids')
    def _compute_operation_count(self):
        for order in self:
            order.operation_count = len(order.operation_ids)

    # ── Helpers ─────────────────────────────────────────────────────

    def _group_expand_stage_ids(self, stages, domain, order):
        return self.env['shop.schedule.stage'].search([], order=order)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('shop.schedule.order') or 'New'
        return super().create(vals_list)

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        if self.lead_id and self.lead_id.partner_id:
            self.partner_id = self.lead_id.partner_id
