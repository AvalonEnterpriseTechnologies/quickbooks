import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

CUSTOM_FIELD_DEFINITIONS_QUERY = """
query CustomFieldDefinitions {
    customFieldDefinitions {
        id
        name
        type
        active
        entityTypes
    }
}
"""


class QBSyncCustomFields(models.AbstractModel):
    _name = 'qb.sync.custom.fields'
    _description = 'QuickBooks Custom Fields Sync'

    def pull(self, client, config, job):
        return self.pull_all(client, config, 'custom_field_definition')

    def push(self, client, config, job):
        _logger.info('Custom field definition writes require partner approval; skipping.')
        return {}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'custom_fields_enabled', False):
            return {'count': 0}
        data = self.env['qb.graphql.client'].execute_graphql(
            config, CUSTOM_FIELD_DEFINITIONS_QUERY,
        )
        definitions = data.get('customFieldDefinitions') or []
        for definition in definitions:
            self._upsert_definition(config, definition)
        return {'count': len(definitions)}

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping custom field definition push_all; definitions are pulled.')
        return {}

    def _upsert_definition(self, config, definition):
        vals = self._definition_vals(config, definition)
        Definition = self.env['ir.model.fields'].sudo()
        existing = Definition.search([
            ('qb_definition_id', '=', vals['qb_definition_id']),
            ('model', '=', vals['model']),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Definition.create(vals)

    def _definition_vals(self, config, definition):
        entity_types = definition.get('entityTypes') or []
        if isinstance(entity_types, list):
            entity_types = ','.join(entity_types)
        model = self._model_for_entity(entity_types)
        field_name = self._manual_field_name(definition)
        return {
            'qb_definition_id': str(definition.get('id') or definition.get('Id') or ''),
            'name': field_name,
            'field_description': definition.get('name') or definition.get('Name') or 'Custom Field',
            'model': model,
            'ttype': self._ttype(definition.get('type') or definition.get('fieldType')),
            'state': 'manual',
            'qb_raw_json': definition,
            'qb_last_synced': fields.Datetime.now(),
        }

    @staticmethod
    def _manual_field_name(definition):
        raw = definition.get('name') or definition.get('Name') or definition.get('id') or 'qb_custom'
        safe = ''.join(ch.lower() if ch.isalnum() else '_' for ch in raw).strip('_')
        return 'x_qb_%s' % (safe or 'custom')

    @staticmethod
    def _ttype(field_type):
        field_type = str(field_type or '').lower()
        if 'date' in field_type:
            return 'date'
        if 'bool' in field_type:
            return 'boolean'
        if 'number' in field_type or 'decimal' in field_type or 'amount' in field_type:
            return 'float'
        return 'char'

    @staticmethod
    def _model_for_entity(entity_types):
        text = str(entity_types or '').lower()
        if 'customer' in text or 'vendor' in text:
            return 'res.partner'
        if 'invoice' in text or 'bill' in text or 'journal' in text:
            return 'account.move'
        if 'item' in text or 'product' in text:
            return 'product.product'
        return 'res.partner'


def extract_custom_field_values(qb_data):
    values = {}
    for custom_field in qb_data.get('CustomField') or []:
        name = custom_field.get('Name') or custom_field.get('DefinitionId')
        if not name:
            continue
        values[name] = (
            custom_field.get('StringValue')
            or custom_field.get('BooleanValue')
            or custom_field.get('DateValue')
            or custom_field.get('NumberValue')
        )
    return values


def build_custom_field_array(values):
    fields_array = []
    for name, value in (values or {}).items():
        fields_array.append({
            'Name': name,
            'Type': 'StringType',
            'StringValue': '' if value is None else str(value),
        })
    return fields_array
