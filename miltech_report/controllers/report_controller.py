import base64

from odoo import http
from odoo.http import content_disposition, request


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
