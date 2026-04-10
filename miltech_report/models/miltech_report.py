import base64
import io
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
        won_domain = self._build_domain(wizard_id, date_field='date_closed')
        return {
            'kpis': self._get_kpis(domain, won_domain),
            'by_stage': self._get_by_stage(domain),
            'by_customer': self._get_by_customer(domain, won_domain),
            'filters': self._get_filter_options(),
        }

    def _is_won_stage(self, stage):
        """A stage counts as won if Odoo marks it is_won OR it's Shipped/Delivered."""
        if stage.is_won:
            return True
        name = (stage.name or '').strip().lower()
        return name in ('shipped', 'delivered')

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

    def _build_domain(self, wizard_id=None, date_field='create_date'):
        """Build search domain. date_field controls which field dates filter on."""
        domain = []
        if not wizard_id:
            return domain

        wizard = self.browse(wizard_id)
        if not wizard.exists():
            return domain

        if wizard.date_from:
            domain.append((date_field, '>=', fields.Datetime.to_string(
                fields.Datetime.start_of(
                    fields.Datetime.from_string(str(wizard.date_from)), 'day'
                )
            )))
        if wizard.date_to:
            domain.append((date_field, '<=', fields.Datetime.to_string(
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

    def _get_kpis(self, domain, won_domain):
        Lead = self.env['crm.lead']

        active_domain = domain + [('active', '=', True)]
        all_leads = Lead.search(active_domain)

        total_leads = len(all_leads)
        total_expected = sum(all_leads.mapped('expected_revenue'))

        won_active = won_domain + [('active', '=', True)]
        won_leads = Lead.search(won_active).filtered(
            lambda l: self._is_won_stage(l.stage_id)
        )
        won_count = len(won_leads)
        won_revenue = sum(won_leads.mapped('expected_revenue'))

        lost_count = self._get_lost_count(domain)

        quoting_leads = all_leads.filtered(
            lambda l: not self._is_won_stage(l.stage_id) and l.expected_revenue > 0
        )
        total_quoted = sum(quoting_leads.mapped('expected_revenue'))

        engagements = self._get_engagements(domain)
        orders_shipped = self._get_orders_shipped(domain)

        return {
            'total_leads': total_leads,
            'total_expected': total_expected,
            'total_quoted': total_quoted,
            'won_count': won_count,
            'won_revenue': won_revenue,
            'lost_count': lost_count,
            'engagements': engagements,
            'orders_shipped': orders_shipped,
        }

    def _get_lost_count(self, domain):
        """Count leads in the 'Lost' stage (active or archived)."""
        Lead = self.env['crm.lead']
        stage = self.env['crm.stage'].search(
            [('name', 'ilike', 'Lost')], limit=1
        )
        if not stage:
            return 0
        lost_domain = domain + [
            ('stage_id', '=', stage.id),
            '|', ('active', '=', True), ('active', '=', False),
        ]
        return Lead.search_count(lost_domain)

    def _get_engagements(self, domain):
        """Count leads in the 'Potential Clients' stage matching current filters."""
        Lead = self.env['crm.lead']
        stage = self.env['crm.stage'].search(
            [('name', 'ilike', 'Potential Clients')], limit=1
        )
        if not stage:
            return 0
        eng_domain = domain + [
            ('stage_id', '=', stage.id),
            ('active', '=', True),
        ]
        return Lead.search_count(eng_domain)

    def _get_orders_shipped(self, domain):
        """Count leads/quotes in the 'Delivered' stage."""
        Lead = self.env['crm.lead']
        stage = self.env['crm.stage'].search(
            ['|', ('name', 'ilike', 'Delivered'), ('name', 'ilike', 'Shipped')], limit=1
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
                'is_won': self._is_won_stage(stage),
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

    def _get_by_customer(self, domain, won_domain):
        Lead = self.env['crm.lead']
        potential_stage = self.env['crm.stage'].search(
            [('name', 'ilike', 'Potential Clients')], limit=1
        )
        exclude = [('stage_id', '!=', potential_stage.id)] if potential_stage else []

        all_domain = domain + exclude + [
            '|', ('active', '=', True), ('active', '=', False),
        ]
        all_leads = Lead.search(all_domain)

        won_leads_domain = won_domain + exclude + [('active', '=', True)]
        won_leads_set = set(
            Lead.search(won_leads_domain).filtered(
                lambda l: self._is_won_stage(l.stage_id)
            ).ids
        )

        partner_map = {}
        other = {
            'partner_name': 'Other',
            'partner_id': False,
            'active_count': 0,
            'quoted_value': 0,
            'won_count': 0,
            'won_value': 0,
            'lost_count': 0,
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
                    }
                bucket = partner_map[pid]

            is_lost_stage = (lead.stage_id.name or '').strip().lower() == 'lost'
            if is_lost_stage:
                bucket['lost_count'] += 1
            elif lead.active:
                bucket['active_count'] += 1
                is_won = self._is_won_stage(lead.stage_id)
                if not is_won:
                    bucket['quoted_value'] += lead.expected_revenue or 0
                if is_won and lead.id in won_leads_set:
                    bucket['won_count'] += 1
                    bucket['won_value'] += lead.expected_revenue or 0

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

        if (other['active_count'] or other['won_count']
                or other['lost_count']):
            total = other['won_count'] + other['lost_count']
            other['win_rate'] = (
                round(other['won_count'] / total * 100, 1) if total else 0
            )
            rows.append(other)

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
    # PDF DATA (used by QWeb report template)
    # -------------------------------------------------------------------------

    @api.model
    def get_pdf_data(self, wizard_id=None):
        """Return dashboard data with all values pre-formatted for the QWeb template."""
        data = self.get_dashboard_data(wizard_id)
        kpis = data['kpis']

        def _fmt_money(v):
            return '${:,.0f}'.format(v) if v else '$0'

        def _fmt_pct(v):
            return '{:.1f}%'.format(v) if v else '0.0%'

        kpi_items = [
            {'label': 'Total Opportunities', 'value': str(kpis['total_leads']), 'color': '#4A6FA5'},
            {'label': 'Total Quoted Value', 'value': _fmt_money(kpis['total_quoted']), 'color': '#F39C12'},
            {'label': 'Quotes Won', 'value': str(kpis['won_count']), 'color': '#27AE60'},
            {'label': 'Won Revenue', 'value': _fmt_money(kpis['won_revenue']), 'color': '#27AE60'},
            {'label': 'Quotes Lost', 'value': str(kpis['lost_count']), 'color': '#E74C3C'},
            {'label': 'Engagements', 'value': str(kpis.get('engagements', 0)), 'color': '#8E44AD'},
            {'label': 'Orders Delivered', 'value': str(kpis.get('orders_shipped', 0)), 'color': '#2980B9'},
        ]

        stage_rows = []
        for s in data['by_stage']:
            stage_rows.append({
                'stage_name': s['stage_name'],
                'is_won': s['is_won'],
                'count': s['count'],
                'total_revenue': _fmt_money(s['total_revenue']),
                'avg_probability': _fmt_pct(s['avg_probability']),
            })

        customer_rows = []
        for c in data['by_customer']:
            customer_rows.append({
                'partner_name': c['partner_name'],
                'active_count': c['active_count'],
                'quoted_value': _fmt_money(c['quoted_value']),
                'won_count': c['won_count'],
                'won_value': _fmt_money(c['won_value']),
                'lost_count': c['lost_count'],
                'win_rate': _fmt_pct(c.get('win_rate', 0)),
            })

        now_str = fields.Datetime.now().strftime('%B %d, %Y at %I:%M %p')
        filter_desc = self._get_filter_description(wizard_id)
        logo_b64 = self._get_logo_base64()

        return {
            'kpi_items': kpi_items,
            'by_stage': stage_rows,
            'by_customer': customer_rows,
            'filter_desc': filter_desc,
            'now_str': now_str,
            'logo_b64': logo_b64,
        }

    def _get_logo_base64(self):
        """Read the Miltech logo and return as base64 string for PDF embedding."""
        try:
            from odoo.modules.module import get_module_resource
            logo_path = get_module_resource(
                'miltech_report', 'static', 'src', 'img', 'miltech_logo.png'
            )
        except Exception:
            logo_path = None
        if not logo_path:
            import os
            logo_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'static', 'src', 'img', 'miltech_logo.png',
            )
        try:
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('ascii')
        except Exception:
            return ''

    def _get_filter_description(self, wizard_id):
        """Build a human-readable string of the active filters."""
        if not wizard_id:
            return 'All Data (No Filters)'
        wizard = self.browse(wizard_id)
        if not wizard.exists():
            return 'All Data (No Filters)'

        parts = []
        if wizard.date_from and wizard.date_to:
            parts.append(f'{wizard.date_from} to {wizard.date_to}')
        elif wizard.date_from:
            parts.append(f'From {wizard.date_from}')
        elif wizard.date_to:
            parts.append(f'Through {wizard.date_to}')
        if wizard.salesperson_id:
            parts.append(f'Salesperson: {wizard.salesperson_id.name}')
        if wizard.partner_id:
            parts.append(f'Customer: {wizard.partner_id.name}')
        if wizard.stage_ids:
            names = ', '.join(wizard.stage_ids.mapped('name'))
            parts.append(f'Stages: {names}')

        return ' | '.join(parts) if parts else 'All Data (No Filters)'

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
            ('Engagements', kpis.get('engagements', 0)),
            ('Orders Delivered', kpis.get('orders_shipped', 0)),
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
        ws3.set_column(0, 6, 20)
        cust_headers = [
            'Customer', 'Active Opps', 'Quoted Value', 'Won',
            'Won Value', 'Lost', 'Win Rate',
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

        workbook.close()
        output.seek(0)
        return output.read()
