import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Each query is shaped against the QuickBooks Online Payroll GraphQL surface
# documented on developer.intuit.com. The connector reads only fields that
# the GraphQL endpoint actually returns, so partially-entitled subscriptions
# (e.g. Core without Tax Setup) degrade gracefully into the smaller subset.

PAYROLL_COMPENSATIONS_QUERY = """
query PayrollEmployeeCompensations {
    payrollEmployeeCompensations {
        employeeId
        compensations {
            id
            name
            type
            active
            rate
            rateType
            effectiveDate
            frequency
            payScheduleId
            defaultHoursPerWeek
        }
    }
}
"""

PAYROLL_EMPLOYEES_QUERY = """
query PayrollEmployees {
    payrollEmployees {
        id
        displayName
        givenName
        familyName
        employmentStatus
        employeeType
        workLocationId
        payScheduleId
        hireDate
        terminationDate
        birthDate
        ssn
        email
        phone
        workersCompClassId
        mailingAddress {
            line1
            line2
            city
            state
            postalCode
            country
        }
        workAddress {
            line1
            line2
            city
            state
            postalCode
            country
        }
        directDeposit {
            bankRoutingNumber
            bankAccountNumber
            accountType
            amount
            allocationType
        }
    }
}
"""

PAYROLL_TAX_SETUP_QUERY = """
query PayrollEmployeeTaxSetup {
    payrollEmployeeTaxSetup {
        employeeId
        federalW4 {
            filingStatus
            multipleJobs
            dependentsAmount
            otherIncome
            deductions
            extraWithholding
            exempt
        }
        stateW4 {
            stateCode
            filingStatus
            allowances
            extraWithholding
            exempt
            additionalFields {
                key
                value
            }
        }
    }
}
"""

PAYROLL_PAY_ITEMS_QUERY = """
query PayrollPayItems {
    payrollPayItems {
        id
        name
        code
        type
        category
        calculationType
        taxability
        glAccountId
        liabilityAccountId
        vendorId
        isYtd
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
        periodStart
        periodEnd
        payDate
        assignedEmployeeIds
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
        checkNumber
        paymentMethod
        journalRefId
        payPeriodStart
        payPeriodEnd
        grossPay
        netPay
        status
        earnings {
            payItemId
            name
            hours
            rate
            amount
        }
        taxes {
            payItemId
            name
            type
            jurisdiction
            employee
            employer
            amount
        }
        deductions {
            payItemId
            name
            type
            employee
            employer
            amount
            isPreTax
        }
        employerContributions {
            payItemId
            name
            amount
        }
        benefits {
            payItemId
            name
            type
            amount
        }
        ytd {
            grossPay
            netPay
            federalIncome
            stateIncome
            fica
            medicare
            futa
            suta
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

    def fetch_employee_tax_setup(self, config):
        return self.execute_graphql(config, PAYROLL_TAX_SETUP_QUERY)

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
