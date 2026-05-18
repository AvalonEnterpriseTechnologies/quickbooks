import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


QBO_CATEGORY_TO_BUCKET = {
    'EARNING': 'earning',
    'EARNINGS': 'earning',
    'WAGE': 'earning',
    'TAX': 'tax',
    'EMPLOYEE_TAX': 'tax',
    'DEDUCTION': 'deduction',
    'PRE_TAX_DEDUCTION': 'deduction',
    'POST_TAX_DEDUCTION': 'deduction',
    'EMPLOYER_CONTRIBUTION': 'employer_contribution',
    'EMPLOYER_TAX': 'employer_contribution',
    'EMPLOYER_BENEFIT': 'employer_contribution',
}

QBO_CALCULATION_TO_TOKEN = {
    'FIXED': 'fixed',
    'FIXED_AMOUNT': 'fixed',
    'PERCENT': 'percent',
    'PERCENTAGE': 'percent',
    'RATE': 'rate',
    'HOURLY_RATE': 'rate',
}

CATEGORY_SEQUENCE = {
    'earning': 10,
    'tax': 30,
    'deduction': 50,
    'employer_contribution': 70,
}

BUCKET_TO_ODOO_CATEGORY_CODE = {
    'earning': 'BASIC',
    'tax': 'DED',
    'deduction': 'DED',
    'employer_contribution': 'COMP',
}


class QBSyncPayrollPayItems(models.AbstractModel):
    _name = 'qb.sync.payroll.pay.items'
    _description = 'QuickBooks Payroll Pay Item Sync'

    def push(self, client, config, job):
        _logger.info('Skipping payroll pay item push; Payroll GraphQL is read-only.')
        return {}

    def pull(self, client, config, job):
        self.pull_all(client, config, job.entity_type)
        return {'qb_id': 'payroll_pay_items_batch'}

    def pull_all(self, client, config, entity_type):
        if not getattr(config, 'payroll_enabled', False):
            return
        data = self.env['qb.payroll.client'].fetch_pay_items(config)
        return self._upsert_pay_items(data, config)

    def push_all(self, client, config, entity_type):
        _logger.info('Skipping payroll pay item push_all; Payroll GraphQL is read-only.')

    def _normalize_bucket(self, value):
        token = str(value or '').strip().upper().replace(' ', '_')
        return QBO_CATEGORY_TO_BUCKET.get(token)

    def _normalize_calculation(self, value):
        token = str(value or '').strip().upper().replace(' ', '_')
        return QBO_CALCULATION_TO_TOKEN.get(token)

    def _find_category(self, bucket):
        if 'hr.salary.rule.category' not in self.env:
            return False
        Category = self.env['hr.salary.rule.category'].sudo()
        code = BUCKET_TO_ODOO_CATEGORY_CODE.get(bucket)
        if not code:
            return False
        category = Category.search([('code', '=', code)], limit=1)
        if category:
            return category
        if code in ('ALW', 'COMP'):
            label = 'Allowance' if code == 'ALW' else 'Employer Contribution'
            return Category.create({
                'code': code,
                'name': '%s (QuickBooks)' % label,
            })
        return False

    def _amount_select_for(self, bucket, calculation):
        if calculation == 'fixed':
            return 'fix'
        if calculation == 'percent':
            return 'percentage'
        return 'code'

    def _amount_expression(self, bucket):
        if bucket == 'tax' or bucket == 'deduction':
            return '-result' if bucket == 'tax' else '-result'
        return 'result'

    def _resolve_account(self, account_ref, config):
        if not account_ref or 'account.account' not in self.env:
            return False
        ref = str(account_ref)
        Account = self.env['account.account'].sudo()
        domain = [('qb_account_id', '=', ref)]
        if 'company_ids' in Account._fields:
            domain.append(('company_ids', 'in', config.company_id.id))
        elif 'company_id' in Account._fields:
            domain.append(('company_id', '=', config.company_id.id))
        match = Account.search(domain, limit=1)
        return match.id if match else False

    def _resolve_vendor(self, vendor_ref, config):
        if not vendor_ref or 'res.partner' not in self.env:
            return False
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([
            ('qb_vendor_id', '=', str(vendor_ref)),
        ], limit=1)
        return partner.id if partner else False

    def _structures_for(self, item, config):
        """Return the Odoo payroll structures this pay item should attach to.

        QBO often defines pay items at the company level; we replicate the
        rule onto every imported pay structure so they're available wherever
        the matching pay schedule is used.
        """
        if 'hr.payroll.structure' not in self.env:
            return self.env['hr.payroll.structure'].sudo()
        Structure = self.env['hr.payroll.structure'].sudo()
        domain = [('qb_pay_schedule_id', '!=', False)]
        if 'company_id' in Structure._fields:
            domain.append(('company_id', '=', config.company_id.id))
        if item.get('payScheduleId'):
            domain.append(('qb_pay_schedule_id', '=', str(item['payScheduleId'])))
        return Structure.search(domain)

    def _upsert_pay_items(self, data, config):
        if 'hr.salary.rule' not in self.env:
            _logger.warning(
                "hr_payroll module not installed - skipping pay item sync"
            )
            return 0
        Rule = self.env['hr.salary.rule'].sudo()
        if 'qb_pay_item_id' not in Rule._fields:
            _logger.warning(
                "QuickBooks payroll bridge fields are not loaded - skipping "
                "pay item sync"
            )
            return 0

        count = 0
        for item in data.get('payrollPayItems', []):
            qb_id = str(item.get('id') or '')
            if not qb_id:
                continue
            if item.get('isYtd'):
                # Odoo computes YTD natively; skip synthetic YTD-only items.
                continue

            bucket = self._normalize_bucket(item.get('category') or item.get('type'))
            calculation = self._normalize_calculation(item.get('calculationType'))
            category = self._find_category(bucket) if bucket else False
            gl_account = self._resolve_account(item.get('glAccountId'), config)
            liability_account = self._resolve_account(
                item.get('liabilityAccountId'), config,
            )
            vendor = self._resolve_vendor(item.get('vendorId'), config)
            structures = self._structures_for(item, config)
            target_structures = structures or self._fallback_structures(config)
            if not target_structures:
                _logger.info(
                    'No payroll structure available for QBO pay item %s; storing rule unattached.',
                    qb_id,
                )

            base_vals = {
                'qb_pay_item_id': qb_id,
                'qb_pay_item_type': item.get('type'),
                'qb_pay_item_category': bucket,
                'qb_pay_item_calculation': calculation,
                'qb_pay_item_tax_jurisdiction': item.get('taxability') or False,
                'qb_gl_account_id': gl_account or False,
                'qb_liability_account_id': liability_account or False,
                'qb_vendor_id': vendor or False,
                'name': item.get('name') or qb_id,
                'code': item.get('code') or qb_id,
                'active': bool(item.get('active', True)),
                'qb_last_synced': fields.Datetime.now(),
                'qb_raw_json': item,
            }
            if bucket and bucket in CATEGORY_SEQUENCE:
                base_vals['sequence'] = CATEGORY_SEQUENCE[bucket]
            if category and 'category_id' in Rule._fields:
                base_vals['category_id'] = category.id
            if 'amount_select' in Rule._fields:
                base_vals['amount_select'] = self._amount_select_for(bucket, calculation)
            if 'condition_select' in Rule._fields:
                base_vals['condition_select'] = 'none'
            if 'account_debit' in Rule._fields and gl_account:
                base_vals['account_debit'] = gl_account
            if 'account_credit' in Rule._fields and liability_account:
                base_vals['account_credit'] = liability_account
            if 'partner_id' in Rule._fields and vendor:
                base_vals['partner_id'] = vendor

            if target_structures:
                for structure in target_structures:
                    vals = dict(base_vals)
                    vals['struct_id'] = structure.id
                    existing = Rule.search([
                        ('qb_pay_item_id', '=', qb_id),
                        ('struct_id', '=', structure.id),
                    ], limit=1)
                    if existing:
                        existing.write(vals)
                    else:
                        Rule.create({k: v for k, v in vals.items() if k in Rule._fields})
            else:
                existing = Rule.search([
                    ('qb_pay_item_id', '=', qb_id),
                ], limit=1)
                vals = {k: v for k, v in base_vals.items() if k in Rule._fields}
                if existing:
                    existing.write(vals)
                elif 'struct_id' not in Rule._fields:
                    Rule.create(vals)
            count += 1
        return count

    def _fallback_structures(self, config):
        if 'hr.payroll.structure' not in self.env:
            return self.env['hr.payroll.structure'].sudo()
        Structure = self.env['hr.payroll.structure'].sudo()
        domain = []
        if 'company_id' in Structure._fields:
            domain.append(('company_id', '=', config.company_id.id))
        return Structure.search(domain)
