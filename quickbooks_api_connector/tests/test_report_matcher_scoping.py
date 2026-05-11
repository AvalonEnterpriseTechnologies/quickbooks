from unittest.mock import patch

from .common import QuickbooksTestCommon


class TestReportMatcherScoping(QuickbooksTestCommon):

    def test_report_account_lookup_uses_functional_account_matcher(self):
        service = self.env['qb.sync.reports']

        with patch.object(
            type(self.env['qb.record.matcher']),
            'find_odoo_match_for_account',
            return_value=self.env['account.account'].browse(),
        ) as matcher:
            service._find_account(self.config, {
                'id': '10',
                'label': 'Checking',
                'path': ['Assets', 'Bank Accounts'],
            })

        self.assertTrue(matcher.called)
        qb_hint = matcher.call_args.args[1]
        self.assertEqual(qb_hint['Id'], '10')
        self.assertEqual(qb_hint['AccountType'], 'Bank')

