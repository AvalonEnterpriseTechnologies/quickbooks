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
        Definition = self.env['quickbooks.custom.field.definition'].sudo()
        existing = Definition.search([
            ('company_id', '=', config.company_id.id),
            ('qb_definition_id', '=', vals['qb_definition_id']),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Definition.create(vals)

    def _definition_vals(self, config, definition):
        entity_types = definition.get('entityTypes') or []
        if isinstance(entity_types, list):
            entity_types = ','.join(entity_types)
        return {
            'company_id': config.company_id.id,
            'qb_definition_id': str(definition.get('id') or definition.get('Id') or ''),
            'name': definition.get('name') or definition.get('Name') or 'Custom Field',
            'entity_type': entity_types,
            'field_type': definition.get('type') or definition.get('fieldType') or '',
            'active': bool(definition.get('active', True)),
            'raw_json': definition,
            'qb_last_synced': fields.Datetime.now(),
        }


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
