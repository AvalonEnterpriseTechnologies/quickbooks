import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class QBSyncProjects(models.AbstractModel):
    _name = 'qb.sync.projects'
    _description = 'QuickBooks Project Sync'

    def _check_model(self):
        if 'project.project' not in self.env:
            _logger.warning('project module not installed; skipping project sync')
            return False
        return True

    def _odoo_project_to_qb_customer(self, project):
        customer_ref = None
        if project.partner_id and project.partner_id.qb_customer_id:
            customer_ref = {
                'value': project.partner_id.qb_customer_id,
                'name': project.partner_id.name,
            }
        payload = {
            'DisplayName': project.name[:100],
            'FullyQualifiedName': project.name[:500],
            'Job': True,
            'IsProject': True,
            'Active': bool(project.active),
        }
        if customer_ref:
            payload['ParentRef'] = customer_ref
        return payload

    def _qb_project_to_odoo(self, qb_data, project_data, config):
        vals = {
            'name': qb_data.get('DisplayName') or qb_data.get('FullyQualifiedName') or 'QBO Project',
            'qb_project_id': str(project_data.get('Id') or qb_data.get('Id') or ''),
            'qb_sync_token': str(qb_data.get('SyncToken') or ''),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
            'company_id': config.company_id.id,
        }
        parent_ref = qb_data.get('ParentRef') or project_data.get('CustomerRef') or {}
        if parent_ref.get('value'):
            vals['qb_customer_id'] = str(parent_ref['value'])
            partner = self.env['res.partner'].search([
                ('qb_customer_id', '=', str(parent_ref['value'])),
            ], limit=1)
            if partner and 'partner_id' in self.env['project.project']._fields:
                vals['partner_id'] = partner.id
        return vals

    def push(self, client, config, job):
        if not self._check_model():
            return {}
        project = self.env['project.project'].browse(job.odoo_record_id)
        if not project.exists():
            return {}

        payload = self._odoo_project_to_qb_customer(project)
        qb_id = project.qb_project_id
        if qb_id:
            existing = client.read('Customer', qb_id).get('Customer', {})
            payload.update({
                'Id': qb_id,
                'SyncToken': existing.get('SyncToken', '0'),
                'sparse': True,
            })
            resp = client.update('Customer', payload)
        else:
            resp = client.create('Customer', payload)

        created = resp.get('Customer', {})
        project_id = str(created.get('Id') or qb_id or '')
        project_payload = {
            'Name': project.name[:100],
            'CustomerRef': {'value': project_id},
            'Active': bool(project.active),
        }
        if project_id:
            try:
                client.post('project', project_payload)
            except Exception:
                _logger.exception('QBO project resource update failed for %s', project.name)

        project.with_context(skip_qb_sync=True).write({
            'qb_project_id': project_id,
            'qb_sync_token': str(created.get('SyncToken') or ''),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': project_id}

    def pull(self, client, config, job):
        if not self._check_model() or not job.qb_entity_id:
            return {}
        resp = client.read('Customer', job.qb_entity_id)
        qb_data = resp.get('Customer', {})
        if not qb_data:
            return {}
        project_data = self._read_project_resource(client, job.qb_entity_id)
        vals = self._qb_project_to_odoo(qb_data, project_data, config)
        existing = self.env['project.project'].search([
            ('qb_project_id', '=', str(qb_data.get('Id'))),
            ('company_id', '=', config.company_id.id),
        ], limit=1)
        if existing:
            existing.with_context(skip_qb_sync=True).write(vals)
        else:
            self.env['project.project'].with_context(skip_qb_sync=True).create(vals)
        return {'qb_id': str(qb_data.get('Id'))}

    def pull_all(self, client, config, entity_type):
        if not self._check_model():
            return
        where = "IsProject = true"
        if config.last_sync_date:
            where += " AND MetaData.LastUpdatedTime > '%s'" % (
                self.env['qb.api.client'].format_qbo_datetime(config.last_sync_date)
            )
        for qb_data in client.query_all('Customer', where_clause=where):
            job = self.env['quickbooks.sync.queue'].new({
                'qb_entity_id': str(qb_data.get('Id')),
            })
            self.pull(client, config, job)

    def push_all(self, client, config, entity_type):
        if not self._check_model():
            return
        projects = self.env['project.project'].search([
            ('qb_project_id', '=', False),
            ('qb_do_not_sync', '=', False),
            ('company_id', 'in', [config.company_id.id, False]),
        ])
        queue = self.env['quickbooks.sync.queue']
        for project in projects:
            queue.enqueue(
                entity_type='project',
                direction='push',
                operation='create',
                odoo_record_id=project.id,
                odoo_model='project.project',
                company=config.company_id,
            )

    def _read_project_resource(self, client, qb_id):
        try:
            return client.get('project/%s' % qb_id).get('Project', {})
        except Exception:
            _logger.debug('QBO project resource not available for customer %s', qb_id)
            return {}
