from odoo import api, models


ACCOUNT_TYPE_FALLBACKS = {
    'Bank': 'asset_cash',
    'Accounts Receivable': 'asset_receivable',
    'Other Current Asset': 'asset_current',
    'Fixed Asset': 'asset_fixed',
    'Other Asset': 'asset_non_current',
    'Accounts Payable': 'liability_payable',
    'Credit Card': 'liability_credit_card',
    'Other Current Liability': 'liability_current',
    'Long Term Liability': 'liability_non_current',
    'Equity': 'equity',
    'Income': 'income',
    'Other Income': 'income_other',
    'Cost of Goods Sold': 'expense_direct_cost',
    'Expense': 'expense',
    'Other Expense': 'expense',
}

ACCOUNT_SUBTYPE_MAP = {
    ('Bank', 'CashOnHand'): 'asset_cash',
    ('Bank', 'Checking'): 'asset_cash',
    ('Bank', 'MoneyMarket'): 'asset_cash',
    ('Bank', 'RentsHeldInTrust'): 'asset_cash',
    ('Bank', 'Savings'): 'asset_cash',
    ('Accounts Receivable', 'AccountsReceivable'): 'asset_receivable',
    ('Other Current Asset', 'AllowanceForBadDebts'): 'asset_current',
    ('Other Current Asset', 'DevelopmentCosts'): 'asset_current',
    ('Other Current Asset', 'EmployeeCashAdvances'): 'asset_current',
    ('Other Current Asset', 'Inventory'): 'asset_current',
    ('Other Current Asset', 'InvestmentMortgageRealEstateLoans'): 'asset_current',
    ('Other Current Asset', 'InvestmentOther'): 'asset_current',
    ('Other Current Asset', 'InvestmentTaxExemptSecurities'): 'asset_current',
    ('Other Current Asset', 'InvestmentUSGovernmentObligations'): 'asset_current',
    ('Other Current Asset', 'LoansToOfficers'): 'asset_current',
    ('Other Current Asset', 'LoansToOthers'): 'asset_current',
    ('Other Current Asset', 'LoansToStockholders'): 'asset_current',
    ('Other Current Asset', 'OtherCurrentAssets'): 'asset_current',
    ('Other Current Asset', 'PrepaidExpenses'): 'asset_prepayments',
    ('Other Current Asset', 'Retainage'): 'asset_current',
    ('Other Current Asset', 'UndepositedFunds'): 'asset_current',
    ('Fixed Asset', 'AccumulatedDepletion'): 'asset_fixed',
    ('Fixed Asset', 'AccumulatedDepreciation'): 'asset_fixed',
    ('Fixed Asset', 'Buildings'): 'asset_fixed',
    ('Fixed Asset', 'DepletableAssets'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetComputers'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetCopiers'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetFurniture'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetPhone'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetPhotoVideo'): 'asset_fixed',
    ('Fixed Asset', 'FixedAssetSoftware'): 'asset_fixed',
    ('Fixed Asset', 'FurnitureAndFixtures'): 'asset_fixed',
    ('Fixed Asset', 'Land'): 'asset_fixed',
    ('Fixed Asset', 'LeaseholdImprovements'): 'asset_fixed',
    ('Fixed Asset', 'OtherFixedAssets'): 'asset_fixed',
    ('Fixed Asset', 'Vehicles'): 'asset_fixed',
    ('Other Asset', 'AccumulatedAmortization'): 'asset_non_current',
    ('Other Asset', 'Goodwill'): 'asset_non_current',
    ('Other Asset', 'LeaseBuyout'): 'asset_non_current',
    ('Other Asset', 'Licenses'): 'asset_non_current',
    ('Other Asset', 'OrganizationalCosts'): 'asset_non_current',
    ('Other Asset', 'OtherLongTermAssets'): 'asset_non_current',
    ('Other Asset', 'SecurityDeposits'): 'asset_non_current',
    ('Accounts Payable', 'AccountsPayable'): 'liability_payable',
    ('Credit Card', 'CreditCard'): 'liability_credit_card',
    ('Other Current Liability', 'DirectDepositPayable'): 'liability_current',
    ('Other Current Liability', 'LineOfCredit'): 'liability_current',
    ('Other Current Liability', 'LoanPayable'): 'liability_current',
    ('Other Current Liability', 'OtherCurrentLiabilities'): 'liability_current',
    ('Other Current Liability', 'PayrollClearing'): 'liability_current',
    ('Other Current Liability', 'PayrollTaxPayable'): 'liability_current',
    ('Other Current Liability', 'PrepaidExpensesPayable'): 'liability_current',
    ('Other Current Liability', 'RentsInTrustLiability'): 'liability_current',
    ('Other Current Liability', 'SalesTaxPayable'): 'liability_current',
    ('Other Current Liability', 'TrustAccountsLiabilities'): 'liability_current',
    ('Long Term Liability', 'NotesPayable'): 'liability_non_current',
    ('Long Term Liability', 'OtherLongTermLiabilities'): 'liability_non_current',
    ('Long Term Liability', 'ShareholderNotesPayable'): 'liability_non_current',
    ('Equity', 'OpeningBalanceEquity'): 'equity_unaffected',
    ('Equity', 'OwnersEquity'): 'equity',
    ('Equity', 'PaidInCapitalOrSurplus'): 'equity',
    ('Equity', 'PartnersEquity'): 'equity',
    ('Equity', 'RetainedEarnings'): 'equity',
    ('Equity', 'TreasuryStock'): 'equity',
    ('Income', 'DiscountsRefundsGiven'): 'income',
    ('Income', 'NonProfitIncome'): 'income',
    ('Income', 'OtherPrimaryIncome'): 'income',
    ('Income', 'SalesOfProductIncome'): 'income',
    ('Income', 'ServiceFeeIncome'): 'income',
    ('Other Income', 'DividendIncome'): 'income_other',
    ('Other Income', 'InterestEarned'): 'income_other',
    ('Other Income', 'OtherInvestmentIncome'): 'income_other',
    ('Other Income', 'OtherMiscellaneousIncome'): 'income_other',
    ('Other Income', 'TaxExemptInterest'): 'income_other',
    ('Cost of Goods Sold', 'CostOfLaborCos'): 'expense_direct_cost',
    ('Cost of Goods Sold', 'EquipmentRentalCos'): 'expense_direct_cost',
    ('Cost of Goods Sold', 'OtherCostsOfServiceCos'): 'expense_direct_cost',
    ('Cost of Goods Sold', 'ShippingFreightDeliveryCos'): 'expense_direct_cost',
    ('Cost of Goods Sold', 'SuppliesMaterialsCogs'): 'expense_direct_cost',
    ('Expense', 'AdvertisingPromotional'): 'expense',
    ('Expense', 'Auto'): 'expense',
    ('Expense', 'BadDebts'): 'expense',
    ('Expense', 'BankCharges'): 'expense',
    ('Expense', 'CharitableContributions'): 'expense',
    ('Expense', 'CommissionsAndFees'): 'expense',
    ('Expense', 'CostOfLabor'): 'expense',
    ('Expense', 'DuesSubscriptions'): 'expense',
    ('Expense', 'Entertainment'): 'expense',
    ('Expense', 'EquipmentRental'): 'expense',
    ('Expense', 'FinanceCosts'): 'expense',
    ('Expense', 'Insurance'): 'expense',
    ('Expense', 'InterestPaid'): 'expense',
    ('Expense', 'LegalProfessionalFees'): 'expense',
    ('Expense', 'MealsEntertainment'): 'expense',
    ('Expense', 'OfficeGeneralAdministrativeExpenses'): 'expense',
    ('Expense', 'PayrollExpenses'): 'expense',
    ('Expense', 'PromotionalMeals'): 'expense',
    ('Expense', 'RentOrLeaseOfBuildings'): 'expense',
    ('Expense', 'RepairMaintenance'): 'expense',
    ('Expense', 'ShippingFreightDelivery'): 'expense',
    ('Expense', 'SuppliesMaterials'): 'expense',
    ('Expense', 'TaxesPaid'): 'expense',
    ('Expense', 'Travel'): 'expense',
    ('Expense', 'TravelMeals'): 'expense',
    ('Expense', 'Utilities'): 'expense',
    ('Other Expense', 'Amortization'): 'expense',
    ('Other Expense', 'Depreciation'): 'expense_depreciation',
    ('Other Expense', 'ExchangeGainOrLoss'): 'expense',
    ('Other Expense', 'OtherMiscellaneousExpense'): 'expense',
    ('Other Expense', 'PenaltiesSettlements'): 'expense',
}

QBO_TYPE_BY_ODOO_TYPE = {
    'asset_cash': 'Bank',
    'asset_receivable': 'Accounts Receivable',
    'asset_current': 'Other Current Asset',
    'asset_prepayments': 'Other Current Asset',
    'asset_fixed': 'Fixed Asset',
    'asset_non_current': 'Other Asset',
    'liability_payable': 'Accounts Payable',
    'liability_credit_card': 'Credit Card',
    'liability_current': 'Other Current Liability',
    'liability_non_current': 'Long Term Liability',
    'equity': 'Equity',
    'equity_unaffected': 'Equity',
    'income': 'Income',
    'income_other': 'Other Income',
    'expense_direct_cost': 'Cost of Goods Sold',
    'expense': 'Expense',
    'expense_depreciation': 'Other Expense',
}

SIBLING_TYPE_GROUPS = (
    ('asset_cash', 'asset_current'),
    ('asset_prepayments', 'asset_current'),
    ('income', 'income_other'),
    ('expense', 'expense_direct_cost', 'expense_depreciation'),
    ('liability_current', 'liability_credit_card'),
)


class QBAccountClassifier(models.AbstractModel):
    _name = 'qb.account.classifier'
    _description = 'QuickBooks Account Classifier'

    @api.model
    def classify(self, qb_account):
        qb_type = (qb_account or {}).get('AccountType') or ''
        qb_subtype = (qb_account or {}).get('AccountSubType') or ''
        odoo_type = (
            ACCOUNT_SUBTYPE_MAP.get((qb_type, qb_subtype))
            or ACCOUNT_TYPE_FALLBACKS.get(qb_type)
            or 'asset_current'
        )
        journal_type = self._journal_type(qb_type, qb_subtype)
        return {
            'qbo_type': qb_type,
            'qbo_subtype': qb_subtype,
            'odoo_type': odoo_type,
            'is_bank_like': journal_type in ('bank', 'cash'),
            'is_credit_card': qb_type == 'Credit Card',
            'preferred_journal_type': journal_type,
        }

    @api.model
    def qbo_type_for_odoo_type(self, odoo_type):
        return QBO_TYPE_BY_ODOO_TYPE.get(odoo_type, 'Expense')

    @api.model
    def compatible_account_types(self, odoo_type):
        compatible = {odoo_type}
        for group in SIBLING_TYPE_GROUPS:
            if odoo_type in group:
                compatible.update(group)
        return list(compatible)

    def _journal_type(self, qb_type, qb_subtype):
        if qb_type == 'Bank':
            return 'cash' if qb_subtype == 'CashOnHand' else 'bank'
        if qb_type == 'Credit Card':
            return 'bank'
        return 'general'
