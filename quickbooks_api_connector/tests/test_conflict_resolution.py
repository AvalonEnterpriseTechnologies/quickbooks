from datetime import datetime, timedelta
from unittest.mock import MagicMock

from odoo import fields

from .common import QuickbooksTestCommon


class TestConflictResolution(QuickbooksTestCommon):

    def _make_partner_and_qb_data(self, odoo_offset_minutes=0, qb_offset_minutes=0):
        """Create a partner and QBO data with configurable timestamps."""
        now = datetime.utcnow()
        partner = self.env['res.partner'].with_context(skip_qb_sync=True).create({
            'name': 'Conflict Partner',
            'customer_rank': 1,
            'qb_customer_id': '100',
        })
        # Manually set write_date
        odoo_dt = now + timedelta(minutes=odoo_offset_minutes)
        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (odoo_dt, partner.id),
        )
        partner.invalidate_recordset()

        qb_dt = now + timedelta(minutes=qb_offset_minutes)
        qb_data = {
            'MetaData': {
                'LastUpdatedTime': qb_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            },
        }
        return partner, qb_data

    def test_last_modified_odoo_wins(self):
        """Odoo is newer → decision should be 'odoo'."""
        partner, qb_data = self._make_partner_and_qb_data(
            odoo_offset_minutes=10, qb_offset_minutes=-10,
        )
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data, 'customer')
        self.assertEqual(decision, 'odoo')

    def test_last_modified_qbo_wins(self):
        """QBO is newer → decision should be 'qbo'."""
        partner, qb_data = self._make_partner_and_qb_data(
            odoo_offset_minutes=-10, qb_offset_minutes=10,
        )
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data, 'customer')
        self.assertEqual(decision, 'qbo')

    def test_odoo_wins_strategy(self):
        """When config says odoo_wins, always return 'odoo'."""
        self.config.conflict_resolution = 'odoo_wins'
        partner, qb_data = self._make_partner_and_qb_data(
            odoo_offset_minutes=-10, qb_offset_minutes=10,
        )
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data, 'customer')
        self.assertEqual(decision, 'odoo')

    def test_qbo_wins_strategy(self):
        """When config says qbo_wins, always return 'qbo'."""
        self.config.conflict_resolution = 'qbo_wins'
        partner, qb_data = self._make_partner_and_qb_data(
            odoo_offset_minutes=10, qb_offset_minutes=-10,
        )
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data, 'customer')
        self.assertEqual(decision, 'qbo')

    def test_manual_strategy(self):
        """When config says manual, always return 'conflict'."""
        self.config.conflict_resolution = 'manual'
        partner, qb_data = self._make_partner_and_qb_data()
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data, 'customer')
        self.assertEqual(decision, 'conflict')

    def test_missing_qb_timestamp(self):
        """Missing QBO timestamp defaults to 'odoo'."""
        partner, _ = self._make_partner_and_qb_data()
        qb_data_no_ts = {'MetaData': {}}
        resolver = self.env['qb.conflict.resolver']
        decision = resolver.resolve(self.config, partner, qb_data_no_ts, 'customer')
        self.assertEqual(decision, 'odoo')

    def test_parse_qb_datetime_formats(self):
        """Test various QBO datetime format parsing."""
        resolver = self.env['qb.conflict.resolver']

        # ISO with Z
        dt = resolver._parse_qb_datetime('2026-01-15T10:30:00Z')
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 10)

        # ISO with milliseconds
        dt = resolver._parse_qb_datetime('2026-01-15T10:30:00.123Z')
        self.assertEqual(dt.minute, 30)

        # ISO with timezone offset
        dt = resolver._parse_qb_datetime('2026-01-15T10:30:00-08:00')
        self.assertEqual(dt.hour, 10)

        # Date only
        dt = resolver._parse_qb_datetime('2026-01-15')
        self.assertEqual(dt.day, 15)
