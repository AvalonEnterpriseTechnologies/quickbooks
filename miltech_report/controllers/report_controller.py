import logging

from odoo import http
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)


class MiltechReportController(http.Controller):

    @http.route(
        '/miltech/xlsx_report',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def download_xlsx(self, wizard_id=None, **kw):
        wizard_id = int(wizard_id) if wizard_id else None
        report_model = request.env['miltech.report'].sudo()
        xlsx_data = report_model.generate_xlsx(wizard_id)

        response = request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition',
                 content_disposition('Miltech_CRM_Report.xlsx')),
            ],
        )
        return response

    @http.route(
        '/miltech/pdf_report',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def download_pdf(self, wizard_id=None, **kw):
        import traceback
        try:
            wizard_id = int(wizard_id) if wizard_id else None
            report_model = request.env['miltech.report'].sudo()

            wizard = report_model.browse(wizard_id) if wizard_id else report_model.create({})
            if not wizard.exists():
                wizard = report_model.create({})

            report = request.env.ref(
                'miltech_report.action_miltech_pdf_report'
            ).sudo()

            pdf_content, _content_type = report._render_qweb_pdf(
                'miltech_report.report_miltech_dashboard',
                res_ids=[wizard.id],
            )

            response = request.make_response(
                pdf_content,
                headers=[
                    ('Content-Type', 'application/pdf'),
                    ('Content-Disposition',
                     content_disposition('Miltech_CRM_Report.pdf')),
                ],
            )
            return response
        except Exception:
            _logger.error('PDF export failed:\n%s', traceback.format_exc())
            raise
