"""Find and merge duplicate hr.employee rows produced by the QBO migration.

Versions of the connector prior to 19.0.8.0.0 created a fresh hr.employee
for every QBO Employee + every QBO Payroll Employee that lacked a
qb_employee_id. After upgrading, the matcher is strong enough to prevent
new duplicates (see qb.record.matcher._find_employee_by_natural_key), but
existing duplicates still need to be cleaned up.

This wizard scans hr.employee for sets of rows sharing the same
work_email / qb_ssn_last4 / normalized name, picks the oldest row in each
group as the master, then merges the rest into the master by:

  * Copying qb_employee_id and any QBO-only blank-on-master fields.
  * Reparenting every Many2one to hr.employee on every model in the
    registry (so hr.contract, hr.payslip, account.analytic.line, etc. are
    all pointed at the kept row).
  * Archiving (active=False) the duplicate row instead of unlinking it,
    so audit trail is preserved.

Each pair runs inside its own savepoint so a single failure does not
abort the whole pass.
"""

import logging
import re

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class QBDedupeEmployeesWizard(models.TransientModel):
    _name = 'qb.dedupe.employees.wizard'
    _description = 'Deduplicate QuickBooks Employee Rows'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    only_active = fields.Boolean(
        string='Only Scan Active Employees',
        default=False,
        help='When off (default), archived employees are still considered '
             'candidates so the wizard can re-collapse old QBO duplicates '
             'that were already deactivated.',
    )
    dry_run = fields.Boolean(default=True)
    preview_message = fields.Text(readonly=True)

    def action_scan(self):
        self.ensure_one()
        groups = self._find_duplicate_groups()
        if not groups:
            self.preview_message = _('No duplicate hr.employee rows were found.')
            return self._reload_wizard_action()
        lines = [
            _('Found %d duplicate group(s) covering %d employee(s):') % (
                len(groups), sum(len(g) for g in groups.values()),
            )
        ]
        for key, employees in list(groups.items())[:50]:
            master = employees[0]
            dups = employees[1:]
            lines.append(' - [%s] master=%s (id=%s); merging %d duplicate(s): %s' % (
                key,
                master.name, master.id, len(dups),
                ', '.join('%s (id=%s)' % (e.name, e.id) for e in dups),
            ))
        if len(groups) > 50:
            lines.append('... and %d more groups not shown' % (len(groups) - 50))
        self.preview_message = '\n'.join(lines)
        return self._reload_wizard_action()

    def action_merge(self):
        self.ensure_one()
        groups = self._find_duplicate_groups()
        merged_pairs = 0
        skipped_pairs = 0
        for key, employees in groups.items():
            master = employees[0]
            for dup in employees[1:]:
                with self.env.cr.savepoint():
                    try:
                        self._merge_pair(master, dup)
                        merged_pairs += 1
                    except Exception:
                        skipped_pairs += 1
                        _logger.exception(
                            'Failed to merge employee %s (id=%s) into %s (id=%s)',
                            dup.name, dup.id, master.name, master.id,
                        )
        self.preview_message = _(
            'Dedupe pass complete: merged %d pair(s), skipped %d pair(s) '
            '(see server log for the per-pair tracebacks).'
        ) % (merged_pairs, skipped_pairs)
        return self._reload_wizard_action()

    def _reload_wizard_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _find_duplicate_groups(self):
        """Return a dict {key: [master, dup, dup, ...]} of duplicate groups.

        Keys are stable (email/ssn/normalized-name) so the master order
        is deterministic across scans. Master = the lowest-id row in the
        group (oldest); the rest are duplicates to merge into it.
        """
        Employee = self.env['hr.employee'].sudo()
        if self.only_active:
            employees = Employee.search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True),
            ])
        else:
            employees = Employee.with_context(active_test=False).search([
                ('company_id', '=', self.company_id.id),
            ])

        buckets = {}
        for emp in employees:
            for key in self._keys_for(emp):
                buckets.setdefault(key, Employee.browse()).__iadd__(emp)

        groups = {}
        for key, recs in buckets.items():
            if len(recs) < 2:
                continue
            ordered = recs.sorted(key=lambda r: (r.id,))
            groups[key] = ordered
        return groups

    def _keys_for(self, employee):
        keys = []
        email = (employee.work_email or '').strip().lower()
        if email:
            keys.append('email:%s' % email)
        ssn4 = (
            getattr(employee, 'qb_ssn_last4', '') or ''
        ).strip()
        if ssn4 and ssn4.isdigit():
            keys.append('ssn4:%s' % ssn4)
        normalized = self._normalize(employee.name)
        if normalized:
            keys.append('name:%s' % normalized)
        return keys

    @staticmethod
    def _normalize(value):
        return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def _merge_pair(self, master, dup):
        if master.id == dup.id:
            return
        if self.dry_run:
            _logger.info(
                '[dry_run] Would merge employee %s (id=%s) into %s (id=%s)',
                dup.name, dup.id, master.name, master.id,
            )
            return

        # Copy QBO link + identifying fields onto the master when the master
        # is missing them; never overwrite an already-populated master field.
        copy_fields = [
            'qb_employee_id', 'qb_intuit_id', 'qb_ssn_last4',
            'qb_hired_date', 'qb_termination_date', 'qb_birth_date',
            'work_email', 'work_phone', 'mobile_phone',
            'birthday',
        ]
        copy_vals = {}
        for fname in copy_fields:
            if fname not in master._fields or fname not in dup._fields:
                continue
            if not master[fname] and dup[fname]:
                copy_vals[fname] = dup[fname]
        if copy_vals:
            master.with_context(skip_qb_sync=True).write(copy_vals)

        # Reparent every Many2one to hr.employee in the registry from
        # dup -> master so contracts, payslips, analytic lines, etc. follow.
        IrField = self.env['ir.model.fields'].sudo()
        m2o_fields = IrField.search([
            ('relation', '=', 'hr.employee'),
            ('ttype', '=', 'many2one'),
            ('store', '=', True),
        ])
        for field in m2o_fields:
            model_name = field.model
            if model_name not in self.env:
                continue
            try:
                Model = self.env[model_name].sudo()
            except Exception:
                continue
            if field.name not in Model._fields:
                continue
            try:
                related = Model.with_context(active_test=False).search([
                    (field.name, '=', dup.id),
                ])
            except Exception:
                continue
            if related:
                try:
                    related.with_context(skip_qb_sync=True).write({
                        field.name: master.id,
                    })
                except Exception:
                    _logger.exception(
                        'Could not reparent %s.%s from emp %s to %s',
                        model_name, field.name, dup.id, master.id,
                    )

        # Archive instead of unlink to preserve audit trail.
        archive_vals = {'active': False}
        if 'qb_do_not_sync' in dup._fields:
            archive_vals['qb_do_not_sync'] = True
        try:
            dup.with_context(skip_qb_sync=True).write(archive_vals)
        except Exception:
            _logger.exception(
                'Could not archive merged duplicate employee id=%s', dup.id,
            )

        _logger.info(
            'Merged employee %s (id=%s) into %s (id=%s); archived duplicate.',
            dup.name, dup.id, master.name, master.id,
        )
