from .common import QuickbooksTestCommon


class TestPayrollExtended(QuickbooksTestCommon):

    def test_pay_items_are_persisted(self):
        data = {
            'payrollPayItems': [{
                'id': 'PI1',
                'name': 'Regular Pay',
                'type': 'earnings',
                'active': True,
            }],
        }

        count = self.env['qb.sync.payroll.pay.items']._upsert_pay_items(
            data, self.config,
        )

        self.assertEqual(count, 1)
        item = self.env['quickbooks.payroll.pay.item'].search([
            ('qb_pay_item_id', '=', 'PI1'),
        ], limit=1)
        self.assertEqual(item.name, 'Regular Pay')

    def test_schedules_are_persisted(self):
        data = {
            'payrollPaySchedules': [{
                'id': 'PS1',
                'name': 'Biweekly',
                'frequency': 'BIWEEKLY',
                'active': True,
                'nextPayDate': '2026-05-15',
            }],
        }

        count = self.env['qb.sync.payroll.schedules']._upsert_schedules(
            data, self.config,
        )

        self.assertEqual(count, 1)
        schedule = self.env['quickbooks.payroll.pay.schedule'].search([
            ('qb_pay_schedule_id', '=', 'PS1'),
        ], limit=1)
        self.assertEqual(schedule.frequency, 'BIWEEKLY')

    def test_checks_are_persisted(self):
        data = {
            'payrollChecks': [{
                'id': 'CHK1',
                'employeeId': 'E1',
                'displayName': 'Payroll Check',
                'checkDate': '2026-05-01',
                'grossPay': 1200.0,
                'netPay': 950.0,
                'status': 'PAID',
            }],
        }

        count = self.env['qb.sync.payroll.checks']._upsert_checks(
            data, self.config,
        )

        self.assertEqual(count, 1)
        check = self.env['quickbooks.payroll.check'].search([
            ('qb_check_id', '=', 'CHK1'),
        ], limit=1)
        self.assertEqual(check.net_pay, 950.0)
