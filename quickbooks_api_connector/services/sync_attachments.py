import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncAttachments(models.AbstractModel):
    _name = 'qb.sync.attachments'
    _description = 'QuickBooks Attachment Sync (pull only)'

    def push(self, client, config, job):
        return {}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Attachable', qb_id)
        qb_data = resp.get('Attachable', {})
        if not qb_data:
            return {}

        file_name = qb_data.get('FileName', 'attachment')
        _logger.info('Pulled attachment metadata: %s (download not implemented)', file_name)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        records = client.query_all('Attachable')
        for qb_data in records:
            _logger.debug(
                'Attachment %s: %s', qb_data.get('Id'), qb_data.get('FileName'),
            )

    def push_all(self, client, config, entity_type):
        pass
