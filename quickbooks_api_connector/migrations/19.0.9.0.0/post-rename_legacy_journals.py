"""Rename the legacy "QuickBooks Journal Entries" and "QuickBooks Opening
Balances" journals so the Odoo journal list stops looking like a QBO-only
dumping ground.

Before 19.0.9.0.0:
  * Every QBO JournalEntry was routed to a single
    ``QuickBooks Journal Entries`` general journal
    (qb_journal_key='qbo:general:default').
  * The opening-balances posting wizard defaulted to a journal called
    ``QuickBooks Opening Balances`` (qb_journal_key='qbo:general:opening').

After 19.0.9.0.0:
  * Each JE is routed to a per-account general journal
    (qb_journal_key='qbo:general:account:<id>') created on demand by
    qb.sync.journals.ensure_general_journal_for_account.
  * The legacy default journal becomes a "Migrated Adjustments (legacy
    fallback)" bucket so existing rows still have a home but new JEs
    no longer land there.
  * The opening-balances journal is renamed to plain "Opening Balances".

This migration only updates display names — it never moves account.move
rows between journals (which would break audit trail). Idempotent: a
re-run silently skips journals that were already renamed.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(env, version):
    if not version:
        return
    if 'account.journal' not in env:
        return
    Journal = env['account.journal'].sudo()

    legacy_default = Journal.search([
        ('qb_journal_key', '=', 'qbo:general:default'),
        ('name', '=', 'QuickBooks Journal Entries'),
    ])
    if legacy_default:
        for journal in legacy_default:
            has_moves = bool(env['account.move'].sudo().search_count([
                ('journal_id', '=', journal.id),
            ]))
            new_name = 'Migrated Adjustments (legacy fallback)'
            vals = {'name': new_name}
            if not has_moves and 'active' in Journal._fields:
                vals['active'] = False
            try:
                journal.write(vals)
            except Exception:
                _logger.exception(
                    '19.0.9.0.0 post-migration: failed to rename legacy QB '
                    'default journal id=%s', journal.id,
                )

    legacy_opening = Journal.search([
        ('qb_journal_key', '=', 'qbo:general:opening'),
        ('name', '=', 'QuickBooks Opening Balances'),
    ])
    if legacy_opening:
        try:
            legacy_opening.write({'name': 'Opening Balances'})
        except Exception:
            _logger.exception(
                '19.0.9.0.0 post-migration: failed to rename legacy QB '
                'opening-balances journal',
            )

    _logger.info(
        '19.0.9.0.0 post-migration: renamed %d legacy default journal(s) '
        'and %d legacy opening journal(s).',
        len(legacy_default), len(legacy_opening),
    )
