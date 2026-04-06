# l10n_us_hr_payroll_ks

Odoo add-on: **Kansas state income tax withholding** (K-4 / KW-100).

Layers on top of `l10n_us_hr_payroll` to add Kansas-specific employee fields,
progressive withholding brackets, and a salary rule that implements the NFC /
KDOR percentage method.

---

## Tax data sources

| Item | Value | Source |
|---|---|---|
| Rates | 5.20 % / 5.58 % (two brackets) | KW-100 `whrates.pdf`, eff. July 1 2024 |
| Standard deduction (Single) | $3,605 | KS Notice 24-08 / SB 1 |
| Standard deduction (Married) | $8,240 | KS Notice 24-08 / SB 1 |
| Personal exemption (Single/HoH 1+ allow.) | $9,160 | NFC-24-1722617728 |
| Personal exemption (Married 2+ allow.) | $18,320 | NFC-24-1722617728 |
| Per-dependent exemption | $2,320 | NFC-24-1722617728 |
| Bracket thresholds (Single) | $0 / $3,605 / $26,605 | NFC-24-1722617728 |
| Bracket thresholds (Married) | $0 / $8,240 / $54,240 | NFC-24-1722617728 |

These rates and exemptions were established by **Senate Bill 1** (2024 Special
Session) and remain current for tax years **2024, 2025, and 2026** -- KDOR has
not published updated withholding tables as of April 2026.

## Install

1. Add this folder to your Odoo addons path.
2. Update the app list and install **United States - Payroll: Kansas Withholding (K-4)**.
3. The post-install hook attaches the `KS_SIT` salary rule to all U.S. payroll structures.

## After install

- Verify the **Kansas Withholding Brackets** and **Kansas Tax Year Parameters**
  records under *Payroll > Configuration* match the current KW-100.
- Confirm `KS_SIT` runs **after** rules that fill the `GROSS` category
  (sequence 350 by default).
- Set each Kansas employee's work address state to **KS** and fill in their
  K-4 filing status and allowances on the new **Kansas K-4** tab.

## Withholding formula (percentage method)

```
1. annual_gross          = period_gross × pay_periods_per_year
2. personal_allowance    = tiered lookup from K-4 allowances + filing status
3. annual_taxable        = max(0, annual_gross − personal_allowance)
4. annual_tax            = walk progressive brackets (base_tax + rate × excess)
5. period_tax            = annual_tax ÷ pay_periods_per_year
6. total_withholding     = period_tax + extra_withholding_per_period
```

## Maintaining tax data

When KDOR publishes new rates or exemptions:

1. Add new bracket rows for the new tax year under *Kansas Withholding Brackets*.
2. Add a new parameter row under *Kansas Tax Year Parameters*.
3. No code changes required -- the salary rule reads from these config records.

## Disclaimer

Tax logic depends on official KDOR publications. This module provides structure
and calculation hooks; **you** are responsible for loading correct table data
and ensuring compliance.
