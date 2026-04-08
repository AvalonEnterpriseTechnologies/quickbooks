import io
import json
from datetime import date, timedelta

from odoo import api, fields, models

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class MiltechReport(models.TransientModel):
    _name = 'miltech.report'
    _description = 'Miltech CRM Report'

    date_from = fields.Date(string='Start Date')
    date_to = fields.Date(string='End Date')
    salesperson_id = fields.Many2one('res.users', string='Salesperson')
    partner_id = fields.Many2one('res.partner', string='Customer')
    stage_ids = fields.Many2many('crm.stage', string='Stages')

    # -------------------------------------------------------------------------
    # PUBLIC API — called from OWL frontend via orm.call()
    # -------------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self, wizard_id=None):
        """Main entry point for the OWL dashboard. Returns all sections."""
        domain = self._build_domain(wizard_id)
        return {
            'kpis': self._get_kpis(domain),
            'by_stage': self._get_by_stage(domain),
            'by_customer': self._get_by_customer(domain),
            'by_salesperson': self._get_by_salesperson(domain),
            'filters': self._get_filter_options(),
        }

    @api.model
    def apply_filters(self, wizard_id, filter_vals):
        """Update the wizard record with new filter values."""
        wizard = self.browse(wizard_id)
        if not wizard.exists():
            wizard_id = self.create({}).id
            wizard = self.browse(wizard_id)

        write_vals = {}
        if 'date_from' in filter_vals:
            write_vals['date_from'] = filter_vals['date_from'] or False
        if 'date_to' in filter_vals:
            write_vals['date_to'] = filter_vals['date_to'] or False
        if 'salesperson_id' in filter_vals:
            write_vals['salesperson_id'] = filter_vals['salesperson_id'] or False
        if 'partner_id' in filter_vals:
            write_vals['partner_id'] = filter_vals['partner_id'] or False
        if 'stage_ids' in filter_vals:
            write_vals['stage_ids'] = [(6, 0, filter_vals['stage_ids'] or [])]

        if write_vals:
            wizard.write(write_vals)

        return self.get_dashboard_data(wizard_id)

    # -------------------------------------------------------------------------
    # DOMAIN BUILDER
    # -------------------------------------------------------------------------

    def _build_domain(self, wizard_id=None):
        domain = []
        if not wizard_id:
            return domain

        wizard = self.browse(wizard_id)
        if not wizard.exists():
            return domain

        if wizard.date_from:
            domain.append(('create_date', '>=', fields.Datetime.to_string(
                fields.Datetime.start_of(
                    fields.Datetime.from_string(str(wizard.date_from)), 'day'
                )
            )))
        if wizard.date_to:
            domain.append(('create_date', '<=', fields.Datetime.to_string(
                fields.Datetime.end_of(
                    fields.Datetime.from_string(str(wizard.date_to)), 'day'
                )
            )))
        if wizard.salesperson_id:
            domain.append(('user_id', '=', wizard.salesperson_id.id))
        if wizard.partner_id:
            domain.append(('partner_id', '=', wizard.partner_id.id))
        if wizard.stage_ids:
            domain.append(('stage_id', 'in', wizard.stage_ids.ids))

        return domain

    # -------------------------------------------------------------------------
    # KPIs
    # -------------------------------------------------------------------------

    def _get_kpis(self, domain):
        Lead = self.env['crm.lead']

        active_domain = domain + [('active', '=', True)]
        all_leads = Lead.search(active_domain)

        total_leads = len(all_leads)
        total_expected = sum(all_leads.mapped('expected_revenue'))

        won_leads = all_leads.filtered(lambda l: l.stage_id.is_won)
        won_count = len(won_leads)
        won_revenue = sum(won_leads.mapped('expected_revenue'))

        lost_domain = domain + [('active', '=', False), ('probability', '=', 0)]
        lost_leads = Lead.search(lost_domain)
        lost_count = len(lost_leads)

        quoting_leads = all_leads.filtered(
            lambda l: not l.stage_id.is_won and l.expected_revenue > 0
        )
        total_quoted = sum(quoting_leads.mapped('expected_revenue'))

        engagements_today = self._get_engagements_today()
        orders_shipped = self._get_orders_shipped(domain)

        return {
            'total_leads': total_leads,
            'total_expected': total_expected,
            'total_quoted': total_quoted,
            'won_count': won_count,
            'won_revenue': won_revenue,
            'lost_count': lost_count,
            'engagements_today': engagements_today,
            'orders_shipped': orders_shipped,
        }

    def _get_engagements_today(self):
        """Count CRM cards created today in the 'Potential Clients' stage."""
        Lead = self.env['crm.lead']
        today_start = fields.Datetime.to_string(
            fields.Datetime.start_of(fields.Datetime.now(), 'day')
        )
        today_end = fields.Datetime.to_string(
            fields.Datetime.end_of(fields.Datetime.now(), 'day')
        )
        stage = self.env['crm.stage'].search(
            [('name', 'ilike', 'Potential Clients')], limit=1
        )
        if not stage:
            return 0
        return Lead.search_count([
            ('stage_id', '=', stage.id),
            ('create_date', '>=', today_start),
            ('create_date', '<=', today_end),
            ('active', '=', True),
        ])

    def _get_orders_shipped(self, domain):
        """Count leads/quotes in the 'Shipped' stage."""
        Lead = self.env['crm.lead']
        stage = self.env['crm.stage'].search(
            [('name', 'ilike', 'Shipped')], limit=1
        )
        if not stage:
            return 0
        shipped_domain = domain + [
            ('stage_id', '=', stage.id),
            '|', ('active', '=', True), ('active', '=', False),
        ]
        return Lead.search_count(shipped_domain)

    # -------------------------------------------------------------------------
    # BY STAGE
    # -------------------------------------------------------------------------

    def _get_by_stage(self, domain):
        Lead = self.env['crm.lead']
        stages = self.env['crm.stage'].search([])
        result = []

        for stage in stages:
            stage_domain = domain + [
                ('stage_id', '=', stage.id),
                '|', ('active', '=', True), ('active', '=', False),
            ]
            leads = Lead.search(stage_domain)
            if not leads:
                continue

            revenues = leads.mapped('expected_revenue')
            probabilities = leads.mapped('probability')

            result.append({
                'stage_id': stage.id,
                'stage_name': stage.name,
                'is_won': stage.is_won,
                'count': len(leads),
                'total_revenue': sum(revenues),
                'avg_probability': (
                    sum(probabilities) / len(probabilities)
                    if probabilities else 0
                ),
            })

        return result

    # -------------------------------------------------------------------------
    # BY CUSTOMER
    # -------------------------------------------------------------------------

    def _get_by_customer(self, domain):
        Lead = self.env['crm.lead']
        has_quote_field = 'x_studio_quote_number' in Lead._fields
        has_po_field = 'x_studio_po_number' in Lead._fields
        all_domain = domain + [
            '|', ('active', '=', True), ('active', '=', False),
        ]
        all_leads = Lead.search(all_domain)

        partner_map = {}
        other = {
            'partner_name': 'Other',
            'partner_id': False,
            'active_count': 0,
            'quoted_value': 0,
            'won_count': 0,
            'won_value': 0,
            'lost_count': 0,
            'quote_numbers': [],
            'po_numbers': [],
        }

        for lead in all_leads:
            partner = lead.partner_id
            if not partner:
                bucket = other
            else:
                pid = partner.id
                if pid not in partner_map:
                    partner_map[pid] = {
                        'partner_name': partner.name,
                        'partner_id': pid,
                        'active_count': 0,
                        'quoted_value': 0,
                        'won_count': 0,
                        'won_value': 0,
                        'lost_count': 0,
                        'quote_numbers': [],
                        'po_numbers': [],
                    }
                bucket = partner_map[pid]

            if lead.active:
                bucket['active_count'] += 1
                if not lead.stage_id.is_won:
                    bucket['quoted_value'] += lead.expected_revenue or 0
                if lead.stage_id.is_won:
                    bucket['won_count'] += 1
                    bucket['won_value'] += lead.expected_revenue or 0
            else:
                if lead.probability == 0:
                    bucket['lost_count'] += 1

            if has_quote_field and lead.x_studio_quote_number:
                bucket['quote_numbers'].append(lead.x_studio_quote_number)
            if has_po_field and lead.x_studio_po_number:
                bucket['po_numbers'].append(lead.x_studio_po_number)

        rows = sorted(
            partner_map.values(),
            key=lambda r: r['won_value'],
            reverse=True,
        )

        for row in rows:
            total = row['won_count'] + row['lost_count']
            row['win_rate'] = (
                round(row['won_count'] / total * 100, 1) if total else 0
            )
            row['quote_numbers'] = ', '.join(row['quote_numbers'])
            row['po_numbers'] = ', '.join(row['po_numbers'])

        if (other['active_count'] or other['won_count']
                or other['lost_count']):
            total = other['won_count'] + other['lost_count']
            other['win_rate'] = (
                round(other['won_count'] / total * 100, 1) if total else 0
            )
            other['quote_numbers'] = ', '.join(other['quote_numbers'])
            other['po_numbers'] = ', '.join(other['po_numbers'])
            rows.append(other)

        return rows

    # -------------------------------------------------------------------------
    # BY SALESPERSON
    # -------------------------------------------------------------------------

    def _get_by_salesperson(self, domain):
        Lead = self.env['crm.lead']
        all_domain = domain + [
            '|', ('active', '=', True), ('active', '=', False),
        ]
        all_leads = Lead.search(all_domain)

        user_map = {}
        for lead in all_leads:
            uid = lead.user_id.id if lead.user_id else 0
            uname = lead.user_id.name if lead.user_id else 'Unassigned'

            if uid not in user_map:
                user_map[uid] = {
                    'user_id': uid,
                    'user_name': uname,
                    'total_opps': 0,
                    'quoted_value': 0,
                    'won_count': 0,
                    'won_revenue': 0,
                    'lost_count': 0,
                }

            entry = user_map[uid]
            entry['total_opps'] += 1

            if lead.active:
                if not lead.stage_id.is_won:
                    entry['quoted_value'] += lead.expected_revenue or 0
                if lead.stage_id.is_won:
                    entry['won_count'] += 1
                    entry['won_revenue'] += lead.expected_revenue or 0
            else:
                if lead.probability == 0:
                    entry['lost_count'] += 1

        rows = sorted(
            user_map.values(),
            key=lambda r: r['won_revenue'],
            reverse=True,
        )

        for row in rows:
            total = row['won_count'] + row['lost_count']
            row['win_rate'] = (
                round(row['won_count'] / total * 100, 1) if total else 0
            )

        return rows

    # -------------------------------------------------------------------------
    # FILTER OPTIONS (for dropdown population)
    # -------------------------------------------------------------------------

    def _get_filter_options(self):
        salespeople = self.env['crm.lead'].search([
            ('user_id', '!=', False),
        ]).mapped('user_id')
        sp_list = [
            {'id': u.id, 'name': u.name}
            for u in salespeople.sorted('name')
        ]

        partners = self.env['crm.lead'].search([
            ('partner_id', '!=', False),
        ]).mapped('partner_id')
        partner_list = [
            {'id': p.id, 'name': p.name}
            for p in partners.sorted('name')
        ]

        stages = self.env['crm.stage'].search([])
        stage_list = [
            {'id': s.id, 'name': s.name}
            for s in stages
        ]

        return {
            'salespeople': sp_list,
            'partners': partner_list,
            'stages': stage_list,
        }

    # -------------------------------------------------------------------------
    # XLSX GENERATION
    # -------------------------------------------------------------------------

    @api.model
    def generate_xlsx(self, wizard_id=None):
        """Generate the XLSX report and return it as base64."""
        data = self.get_dashboard_data(wizard_id)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # -- Formats --
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 18, 'align': 'center',
            'font_color': '#FFFFFF', 'bg_color': '#1B2A4A',
            'border': 1,
        })
        header_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center',
            'font_color': '#FFFFFF', 'bg_color': '#4A6FA5',
            'border': 1,
        })
        kpi_label_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'right',
            'border': 1,
        })
        kpi_value_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'left',
            'font_color': '#1B2A4A', 'border': 1,
        })
        money_fmt = workbook.add_format({
            'num_format': '$#,##0.00', 'align': 'center', 'border': 1,
        })
        pct_fmt = workbook.add_format({
            'num_format': '0.0%', 'align': 'center', 'border': 1,
        })
        num_fmt = workbook.add_format({
            'align': 'center', 'border': 1,
        })
        text_fmt = workbook.add_format({
            'align': 'left', 'border': 1, 'text_wrap': True,
        })

        # =====================================================================
        # SHEET 1: Dashboard KPIs
        # =====================================================================
        ws = workbook.add_worksheet('Dashboard')
        ws.set_column(0, 6, 22)
        ws.merge_range('A1:G1', 'MILTECH CRM DASHBOARD', title_fmt)

        kpis = data['kpis']
        kpi_items = [
            ('Total Opportunities', kpis['total_leads']),
            ('Total Quoted Value', kpis['total_quoted']),
            ('Quotes Won', kpis['won_count']),
            ('Won Revenue', kpis['won_revenue']),
            ('Quotes Lost', kpis['lost_count']),
            ('Engagements Today', kpis.get('engagements_today', 0)),
            ('Orders Shipped', kpis.get('orders_shipped', 0)),
        ]
        for i, (label, value) in enumerate(kpi_items):
            row = 2 + i
            ws.write(row, 0, label, kpi_label_fmt)
            if isinstance(value, float) and value > 100:
                ws.write(row, 1, value, money_fmt)
            else:
                ws.write(row, 1, value, kpi_value_fmt)

        # =====================================================================
        # SHEET 2: By Stage
        # =====================================================================
        ws2 = workbook.add_worksheet('Pipeline by Stage')
        ws2.set_column(0, 4, 22)
        stage_headers = ['Stage', 'Count', 'Total Revenue', 'Avg Probability']
        for i, h in enumerate(stage_headers):
            ws2.write(0, i, h, header_fmt)
        for row_idx, s in enumerate(data['by_stage'], 1):
            ws2.write(row_idx, 0, s['stage_name'], text_fmt)
            ws2.write(row_idx, 1, s['count'], num_fmt)
            ws2.write(row_idx, 2, s['total_revenue'], money_fmt)
            ws2.write(row_idx, 3, s['avg_probability'] / 100, pct_fmt)

        # =====================================================================
        # SHEET 3: By Customer
        # =====================================================================
        ws3 = workbook.add_worksheet('Pipeline by Customer')
        ws3.set_column(0, 8, 20)
        cust_headers = [
            'Customer', 'Active Opps', 'Quoted Value', 'Won',
            'Won Value', 'Lost', 'Win Rate', 'Quote Numbers', 'PO Numbers',
        ]
        for i, h in enumerate(cust_headers):
            ws3.write(0, i, h, header_fmt)
        for row_idx, c in enumerate(data['by_customer'], 1):
            ws3.write(row_idx, 0, c['partner_name'], text_fmt)
            ws3.write(row_idx, 1, c['active_count'], num_fmt)
            ws3.write(row_idx, 2, c['quoted_value'], money_fmt)
            ws3.write(row_idx, 3, c['won_count'], num_fmt)
            ws3.write(row_idx, 4, c['won_value'], money_fmt)
            ws3.write(row_idx, 5, c['lost_count'], num_fmt)
            ws3.write(row_idx, 6, c['win_rate'] / 100, pct_fmt)
            ws3.write(row_idx, 7, c.get('quote_numbers', ''), text_fmt)
            ws3.write(row_idx, 8, c.get('po_numbers', ''), text_fmt)

        # =====================================================================
        # SHEET 4: By Salesperson
        # =====================================================================
        ws4 = workbook.add_worksheet('Pipeline by Salesperson')
        ws4.set_column(0, 5, 22)
        sp_headers = [
            'Salesperson', 'Total Opps', 'Quoted Value',
            'Won', 'Won Revenue', 'Win Rate',
        ]
        for i, h in enumerate(sp_headers):
            ws4.write(0, i, h, header_fmt)
        for row_idx, s in enumerate(data['by_salesperson'], 1):
            ws4.write(row_idx, 0, s['user_name'], text_fmt)
            ws4.write(row_idx, 1, s['total_opps'], num_fmt)
            ws4.write(row_idx, 2, s['quoted_value'], money_fmt)
            ws4.write(row_idx, 3, s['won_count'], num_fmt)
            ws4.write(row_idx, 4, s['won_revenue'], money_fmt)
            ws4.write(row_idx, 5, s['win_rate'] / 100, pct_fmt)

        workbook.close()
        output.seek(0)
        return output.read()
