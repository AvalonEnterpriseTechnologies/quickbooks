from odoo import http
from odoo.http import content_disposition, request


class ProjectTaskPersonReportController(http.Controller):

    @http.route(
        '/project_task_person_report/pdf/<int:wizard_id>',
        type='http',
        auth='user',
        methods=['GET'],
    )
    def download_pdf(self, wizard_id, **kw):
        wizard = request.env['project.task.person.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            return request.not_found()

        wizard._refresh_lines()
        report = request.env.ref(
            'project_task_person_report.action_report_project_task_person'
        )
        pdf_content, _content_type = report._render_qweb_pdf(
            'project_task_person_report.report_project_task_person',
            res_ids=[wizard.id],
        )

        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                (
                    'Content-Disposition',
                    content_disposition('Project_Open_Tasks_by_Person_Report.pdf'),
                ),
            ],
        )
