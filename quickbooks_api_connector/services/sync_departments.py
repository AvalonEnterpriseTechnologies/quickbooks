import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncDepartments(models.AbstractModel):
    _name = 'qb.sync.departments'
    _description = 'QuickBooks Department Sync'

    def _check_model(self):
        if 'account.analytic.account' not in self.env:
            _logger.warning("analytic accounting not installed — skipping department sync")
            return False
        return True

    def _department_plan(self, company):
        Plan = self.env['account.analytic.plan'].sudo()
        plan = Plan.search([
            ('name', '=', 'QuickBooks Departments'),
            ('company_id', 'in', [company.id, False]),
        ], limit=1)
        if not plan:
            vals = {'name': 'QuickBooks Departments'}
            if 'company_id' in Plan._fields:
                vals['company_id'] = company.id
            plan = Plan.create(vals)
        return plan

    def _qb_department_to_odoo(self, qb_data):
        vals = {
            'name': qb_data.get('Name', 'Unknown'),
            'qb_department_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        }
        if 'active' in self.env['account.analytic.account']._fields:
            vals['active'] = bool(qb_data.get('Active', True))
        return vals

    def push(self, client, config, job):
        if not self._check_model():
            return {}
        dept = self.env['account.analytic.account'].browse(job.odoo_record_id)
        if not dept.exists():
            return {}
        payload = {'Name': dept.name}
        qb_id = dept.qb_department_id
        matcher = self.env['qb.record.matcher']
        if not qb_id:
            entity = matcher.find_qbo_match(client, 'department', dept)
            if entity:
                qb_id = str(entity.get('Id', ''))
                matcher.link_odoo_record(dept, 'department', entity)
        if qb_id:
            existing = client.read('Department', qb_id)
            entity = existing.get('Department', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Department', payload)
        else:
            resp = client.create('Department', payload)
        created = resp.get('Department', {})
        dept.write({
            'qb_department_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
        })
        return {'qb_id': str(created.get('Id', ''))}

    def pull(self, client, config, job):
        if not self._check_model():
            return {}
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Department', qb_id)
        qb_data = resp.get('Department', {})
        if not qb_data:
            return {}
        vals = self._qb_department_to_odoo(qb_data)
        vals['plan_id'] = self._department_plan(config.company_id).id
        matcher = self.env['qb.record.matcher']
        existing = matcher.find_odoo_match('department', qb_data, config.company_id)
        if existing:
            matcher.link_odoo_record(existing, 'department', qb_data)
            existing.write(vals)
        else:
            self.env['account.analytic.account'].create(vals)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        records = client.query_all('Department', where_clause=where)
        Dept = self.env['account.analytic.account']
        plan = self._department_plan(config.company_id)
        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_department_to_odoo(qb_data)
            vals['plan_id'] = plan.id
            matcher = self.env['qb.record.matcher']
            existing = matcher.find_odoo_match('department', qb_data, config.company_id)
            if existing:
                matcher.link_odoo_record(existing, 'department', qb_data)
                existing.write(vals)
            else:
                Dept.create(vals)

    def push_all(self, client, config, entity_type):
        if not self._check_model():
            return
        departments = self.env['account.analytic.account'].search([
            ('qb_department_id', '=', False),
            ('plan_id', '=', self._department_plan(config.company_id).id),
        ])
        queue = self.env['quickbooks.sync.queue']
        for department in departments:
            queue.enqueue(
                entity_type='department',
                direction='push',
                operation='create',
                odoo_record_id=department.id,
                odoo_model='account.analytic.account',
                company=config.company_id,
            )
