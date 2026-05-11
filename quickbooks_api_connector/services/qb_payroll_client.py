import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PAYROLL_COMPENSATIONS_QUERY = """
query PayrollEmployeeCompensations {
    payrollEmployeeCompensations {
        employeeId
        compensations {
            id
            name
            type
            active
        }
    }
}
"""

PAYROLL_EMPLOYEES_QUERY = """
query PayrollEmployees {
    payrollEmployees {
        id
        displayName
        employmentStatus
        workLocationId
        payScheduleId
        hireDate
        terminationDate
    }
}
"""

PAYROLL_PAY_ITEMS_QUERY = """
query PayrollPayItems {
    payrollPayItems {
        id
        name
        type
        active
    }
}
"""

PAYROLL_PAY_SCHEDULES_QUERY = """
query PayrollPaySchedules {
    payrollPaySchedules {
        id
        name
        frequency
        active
        nextPayDate
    }
}
"""

PAYROLL_CHECKS_QUERY = """
query PayrollChecks($startDate: String, $endDate: String) {
    payrollChecks(startDate: $startDate, endDate: $endDate) {
        id
        employeeId
        displayName
        checkDate
        payPeriodStart
        payPeriodEnd
        grossPay
        netPay
        status
        deductions {
            name
            type
            amount
        }
        benefits {
            name
            type
            amount
        }
    }
}
"""

class QBPayrollClient(models.AbstractModel):
    _name = 'qb.payroll.client'
    _inherit = 'qb.graphql.client'
    _description = 'QuickBooks Payroll GraphQL Client'

    def fetch_compensations(self, config):
        return self.execute_graphql(config, PAYROLL_COMPENSATIONS_QUERY)

    def fetch_payroll_employees(self, config):
        return self.execute_graphql(config, PAYROLL_EMPLOYEES_QUERY)

    def fetch_pay_items(self, config):
        return self.execute_graphql(config, PAYROLL_PAY_ITEMS_QUERY)

    def fetch_pay_schedules(self, config):
        return self.execute_graphql(config, PAYROLL_PAY_SCHEDULES_QUERY)

    def fetch_checks(self, config, start_date=None, end_date=None):
        variables = {
            'startDate': start_date.isoformat() if hasattr(start_date, 'isoformat') else start_date,
            'endDate': end_date.isoformat() if hasattr(end_date, 'isoformat') else end_date,
        }
        return self.execute_graphql(config, PAYROLL_CHECKS_QUERY, variables)
