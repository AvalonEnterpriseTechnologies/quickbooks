import logging
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBConflictResolver(models.AbstractModel):
    _name = 'qb.conflict.resolver'
    _description = 'QuickBooks Conflict Resolver'

    def resolve(self, config, odoo_record, qb_data, entity_type):
        """
        Determine which side wins when both have been modified.

        Returns:
            'odoo'  - Odoo record should overwrite QBO
            'qbo'   - QBO data should overwrite Odoo
            'conflict' - Needs manual review
            'skip'  - No changes needed
        """
        strategy = config.conflict_resolution

        if strategy == 'odoo_wins':
            return 'odoo'
        if strategy == 'qbo_wins':
            return 'qbo'
        if strategy == 'manual':
            return 'conflict'

        # last_modified strategy
        odoo_write_date = odoo_record.write_date
        qb_updated_str = (
            qb_data.get('MetaData', {}).get('LastUpdatedTime', '')
        )

        if not qb_updated_str:
            return 'odoo'
        if not odoo_write_date:
            return 'qbo'

        try:
            qb_updated = self._parse_qb_datetime(qb_updated_str)
        except (ValueError, TypeError):
            _logger.warning('Could not parse QBO datetime: %s', qb_updated_str)
            return 'odoo'

        odoo_dt = odoo_write_date.replace(tzinfo=None)
        if odoo_dt > qb_updated:
            return 'odoo'
        elif qb_updated > odoo_dt:
            return 'qbo'
        else:
            return 'skip'

    @staticmethod
    def _parse_qb_datetime(dt_str):
        """Parse QBO ISO datetime string to naive UTC datetime."""
        dt_str = dt_str.replace('Z', '+00:00')
        if '+' in dt_str:
            dt_str = dt_str.split('+')[0]
        elif dt_str.count('-') > 2:
            parts = dt_str.rsplit('-', 1)
            dt_str = parts[0]

        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        raise ValueError('Cannot parse datetime: %s' % dt_str)
