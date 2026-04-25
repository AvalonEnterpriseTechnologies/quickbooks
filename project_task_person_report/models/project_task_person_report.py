from collections import defaultdict

from odoo import api, fields, models


CLOSED_TASK_STATES = [
    '1_done',
    '1_canceled',
    'done',
    'cancel',
    'cancelled',
    'canceled',
    'closed',
]


class ProjectTaskPersonReportWizard(models.TransientModel):
    _name = 'project.task.person.report.wizard'
    _description = 'Project Open Tasks by Person Report'
    _rec_name = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        readonly=True,
        default='Project Open Tasks by Person Report',
    )
    report_date = fields.Date(
        string='Report Date',
        required=True,
        readonly=True,
        default=lambda self: fields.Date.context_today(self),
    )
    line_ids = fields.One2many(
        'project.task.person.report.line',
        'wizard_id',
        string='Report Lines',
        readonly=True,
    )

    @api.model
    def action_open_report(self):
        wizard = self.create({'report_date': fields.Date.context_today(self)})
        wizard._refresh_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Project Open Tasks by Person Report',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'current',
        }

    def action_refresh(self):
        self._refresh_lines()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_print_pdf(self):
        self._refresh_lines()
        return self.env.ref(
            'project_task_person_report.action_report_project_task_person'
        ).report_action(self)

    def _refresh_lines(self):
        for wizard in self:
            wizard.line_ids.unlink()
            wizard.write({
                'report_date': fields.Date.context_today(wizard),
                'line_ids': wizard._prepare_line_commands(),
            })

    def _prepare_line_commands(self):
        project_counts = self._get_project_counts_by_creator()
        task_created_counts = self._get_task_counts_by_creator()
        task_counts, late_counts = self._get_open_task_counts_by_assignee()
        user_ids = (
            set(project_counts)
            | set(task_created_counts)
            | set(task_counts)
            | set(late_counts)
        )
        users = self.env['res.users'].browse(user_ids).exists().sorted(
            lambda user: (user.name or '').lower()
        )

        return [
            (
                0,
                0,
                {
                    'user_id': user.id,
                    'open_project_count': project_counts[user.id],
                    'task_created_count': task_created_counts[user.id],
                    'open_task_count': task_counts[user.id],
                    'late_task_count': late_counts[user.id],
                },
            )
            for user in users
        ]

    def _get_project_counts_by_creator(self):
        Project = self.env['project.project']
        return self._get_counts_by_creator(Project, self._get_project_domain(Project))

    def _get_project_domain(self, Project):
        domain = []
        if 'active' in Project._fields:
            domain.append(('active', '=', True))
        if 'is_template' in Project._fields:
            domain.append(('is_template', '!=', True))
        return domain

    def _get_task_counts_by_creator(self):
        Task = self.env['project.task']
        return self._get_counts_by_creator(Task, self._get_project_task_domain(Task))

    def _get_counts_by_creator(self, Model, domain):
        counts = defaultdict(int)
        for record in Model.search(domain):
            if record.create_uid:
                counts[record.create_uid.id] += 1
        return counts

    def _get_open_task_counts_by_assignee(self):
        Task = self.env['project.task']
        today = fields.Date.context_today(self)
        counts = defaultdict(int)
        late_counts = defaultdict(int)

        for task in Task.search(self._get_open_task_domain(Task)):
            for user in task.user_ids:
                counts[user.id] += 1
                deadline = fields.Date.to_date(task.date_deadline)
                if deadline and deadline < today:
                    late_counts[user.id] += 1

        return counts, late_counts

    def _get_project_task_domain(self, Task):
        domain = []

        if 'active' in Task._fields:
            domain.append(('active', '=', True))
        if 'project_id' in Task._fields:
            domain.append(('project_id', '!=', False))
        if 'has_project_template' in Task._fields:
            domain.append(('has_project_template', '!=', True))

        return domain

    def _get_open_task_domain(self, Task):
        domain = self._get_project_task_domain(Task)

        if 'is_closed' in Task._fields:
            domain.append(('is_closed', '=', False))
        elif 'state' in Task._fields:
            domain.append(('state', 'not in', CLOSED_TASK_STATES))

        if 'date_end' in Task._fields:
            domain.append(('date_end', '=', False))

        if (
            'stage_id' in Task._fields
            and 'fold' in self.env['project.task.type']._fields
        ):
            domain += ['|', ('stage_id', '=', False), ('stage_id.fold', '=', False)]

        return domain

    def _get_late_task_domain(self, Task, user=None):
        domain = self._get_open_task_domain(Task)
        domain += [
            ('date_deadline', '!=', False),
            ('date_deadline', '<', fields.Date.context_today(self)),
        ]
        if user:
            domain.append(('user_ids', 'in', user.ids))
        return domain


class ProjectTaskPersonReportLine(models.TransientModel):
    _name = 'project.task.person.report.line'
    _description = 'Project Open Tasks by Person Report Line'
    _order = 'user_id'

    wizard_id = fields.Many2one(
        'project.task.person.report.wizard',
        required=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one('res.users', string='Person', required=True, readonly=True)
    open_project_count = fields.Integer(string='Projects Created', readonly=True)
    task_created_count = fields.Integer(string='Tasks Created', readonly=True)
    open_task_count = fields.Integer(string='Open Tasks', readonly=True)
    late_task_count = fields.Integer(string='Late Tasks', readonly=True)

    def action_view_late_tasks(self):
        self.ensure_one()
        Task = self.env['project.task']
        domain = self.env['project.task.person.report.wizard']._get_late_task_domain(
            Task,
            self.user_id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Late Tasks - %s' % self.user_id.name,
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }
