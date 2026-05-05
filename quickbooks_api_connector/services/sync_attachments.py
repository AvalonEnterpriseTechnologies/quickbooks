import base64
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    import requests as http_requests
except ImportError:
    http_requests = None

_logger = logging.getLogger(__name__)


class QBSyncAttachments(models.AbstractModel):
    _name = 'qb.sync.attachments'
    _description = 'QuickBooks Attachment Sync'

    def _find_odoo_target(self, qb_data):
        refs = qb_data.get('AttachableRef') or []
        if not refs:
            return {}
        entity_ref = (refs[0].get('EntityRef') or {})
        qb_type = entity_ref.get('type')
        qb_id = str(entity_ref.get('value', ''))
        if not qb_id:
            return {}
        entity_types = {
            'Invoice': 'invoice',
            'Bill': 'bill',
            'CreditMemo': 'credit_memo',
            'VendorCredit': 'vendor_credit',
            'JournalEntry': 'journal_entry',
            'Payment': 'payment',
            'BillPayment': 'bill_payment',
            'Customer': 'customer',
            'Vendor': 'vendor',
        }
        entity_type = entity_types.get(qb_type)
        if not entity_type:
            return {}
        record = self.env['qb.record.matcher'].find_odoo_match(
            entity_type, {'Id': qb_id}, self.env.company,
        )
        if not record:
            return {}
        return {'res_model': record._name, 'res_id': record.id}

    def _attachment_entity_ref(self, attachment):
        if attachment.res_model == 'account.move' and attachment.res_id:
            move = self.env['account.move'].browse(attachment.res_id)
            candidates = [
                ('Invoice', getattr(move, 'qb_invoice_id', False)),
                ('Bill', getattr(move, 'qb_bill_id', False)),
                ('CreditMemo', getattr(move, 'qb_creditmemo_id', False)),
                ('VendorCredit', getattr(move, 'qb_vendorcredit_id', False)),
                ('JournalEntry', getattr(move, 'qb_je_id', False)),
            ]
        elif attachment.res_model == 'account.payment' and attachment.res_id:
            payment = self.env['account.payment'].browse(attachment.res_id)
            candidates = [
                ('Payment', getattr(payment, 'qb_payment_id', False)),
                ('BillPayment', getattr(payment, 'qb_billpayment_id', False)),
            ]
        else:
            return None
        for qb_type, qb_id in candidates:
            if qb_id:
                return {'type': qb_type, 'value': qb_id}
        return None

    def push(self, client, config, job):
        if http_requests is None:
            raise UserError('The "requests" Python library is required for attachment upload.')
        attachment = self.env['ir.attachment'].browse(job.odoo_record_id)
        if not attachment.exists() or not attachment.datas:
            return {}
        entity_ref = self._attachment_entity_ref(attachment)
        if not entity_ref:
            return {}

        metadata = {
            'AttachableRef': [{'EntityRef': entity_ref}],
            'FileName': attachment.name or 'attachment',
            'ContentType': attachment.mimetype or 'application/octet-stream',
        }
        token = client._auth_service.ensure_token_valid(config)
        url = client._append_minor_version('%s/upload' % client._api_prefix)
        headers = {
            'Authorization': 'Bearer %s' % token,
            'Accept': 'application/json',
        }
        file_content = base64.b64decode(attachment.datas)
        files = {
            'file_metadata_01': (
                'attachment.json', json.dumps(metadata), 'application/json',
            ),
            'file_content_01': (
                attachment.name or 'attachment',
                file_content,
                attachment.mimetype or 'application/octet-stream',
            ),
        }
        resp = http_requests.post(url, headers=headers, files=files, timeout=120)
        if resp.status_code >= 400:
            raise UserError('QBO attachment upload failed: %s' % resp.text[:500])
        attachable = resp.json().get('AttachableResponse', [{}])[0].get('Attachable', {})
        return {'qb_id': str(attachable.get('Id', ''))}

    def pull(self, client, config, job):
        qb_id = job.qb_entity_id
        if not qb_id:
            return {}
        resp = client.read('Attachable', qb_id)
        qb_data = resp.get('Attachable', {})
        if not qb_data:
            return {}

        file_name = qb_data.get('FileName', 'attachment')
        file_url = qb_data.get('FileAccessUri')
        if file_url and http_requests is not None:
            response = http_requests.get(file_url, timeout=120)
            if response.status_code < 400:
                vals = {
                    'name': file_name,
                    'datas': base64.b64encode(response.content),
                    'mimetype': qb_data.get('ContentType') or response.headers.get('content-type'),
                    'description': qb_data.get('Note'),
                }
                vals.update(self._find_odoo_target(qb_data))
                self.env['ir.attachment'].sudo().create(vals)
            else:
                _logger.warning(
                    'Attachment download failed for %s: %s',
                    file_name, response.status_code,
                )
        else:
            _logger.info('Pulled attachment metadata without file URL: %s', file_name)
        return {'qb_id': str(qb_data.get('Id', ''))}

    def pull_all(self, client, config, entity_type):
        records = client.query_all('Attachable')
        for qb_data in records:
            job = self.env['quickbooks.sync.queue'].new({
                'qb_entity_id': str(qb_data.get('Id', '')),
            })
            self.pull(client, config, job)

    def push_all(self, client, config, entity_type):
        attachments = self.env['ir.attachment'].search([
            ('res_model', 'in', ('account.move', 'account.payment')),
            ('datas', '!=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for attachment in attachments:
            queue.enqueue(
                entity_type='attachment',
                direction='push',
                operation='create',
                odoo_record_id=attachment.id,
                odoo_model='ir.attachment',
                company=config.company_id,
            )
