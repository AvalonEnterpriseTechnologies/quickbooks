import json
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class QuickbooksTestCommon(TransactionCase):
    """Shared test fixtures and mock API helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['quickbooks.config'].create({
            'company_id': cls.company.id,
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'realm_id': '123456789',
            'environment': 'sandbox',
            'state': 'connected',
            'webhook_verifier_token': 'test_verifier_token',
            'conflict_resolution': 'last_modified',
        })
        # Set tokens directly (encrypted)
        cls.config.set_tokens('test_access_token', 'test_refresh_token', 3600)

    def _mock_client(self):
        """Return a mock _QBClient with common responses pre-configured."""
        client = MagicMock()
        client.get.return_value = {}
        client.post.return_value = {}
        client.query.return_value = {'QueryResponse': {}}
        client.read.return_value = {}
        client.create.return_value = {}
        client.update.return_value = {}
        client.delete.return_value = {}
        client.query_all.return_value = []
        return client

    def _make_qb_customer(self, qb_id='100', name='Test Customer'):
        return {
            'Customer': {
                'Id': qb_id,
                'SyncToken': '0',
                'DisplayName': name,
                'GivenName': name.split()[0],
                'FamilyName': ' '.join(name.split()[1:]) or '',
                'PrimaryEmailAddr': {'Address': 'test@example.com'},
                'PrimaryPhone': {'FreeFormNumber': '555-1234'},
                'BillAddr': {
                    'Line1': '123 Test St',
                    'City': 'Testville',
                    'CountrySubDivisionCode': 'CA',
                    'PostalCode': '90210',
                    'Country': 'US',
                },
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_vendor(self, qb_id='200', name='Test Vendor'):
        return {
            'Vendor': {
                'Id': qb_id,
                'SyncToken': '0',
                'DisplayName': name,
                'PrimaryEmailAddr': {'Address': 'vendor@example.com'},
                'PrimaryPhone': {'FreeFormNumber': '555-5678'},
                'BillAddr': {
                    'Line1': '456 Vendor Ave',
                    'City': 'Vendortown',
                },
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_item(self, qb_id='300', name='Test Item'):
        return {
            'Item': {
                'Id': qb_id,
                'SyncToken': '0',
                'Name': name,
                'Type': 'NonInventory',
                'UnitPrice': 99.99,
                'PurchaseCost': 50.00,
                'Sku': 'TEST-001',
                'Active': True,
                'Description': 'A test product',
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_invoice(self, qb_id='400', customer_id='100'):
        return {
            'Invoice': {
                'Id': qb_id,
                'SyncToken': '0',
                'CustomerRef': {'value': customer_id, 'name': 'Test Customer'},
                'TxnDate': '2026-01-15',
                'DueDate': '2026-02-15',
                'DocNumber': 'INV-001',
                'TotalAmt': 199.98,
                'Line': [
                    {
                        'DetailType': 'SalesItemLineDetail',
                        'Amount': 199.98,
                        'Description': 'Test line item',
                        'SalesItemLineDetail': {
                            'Qty': 2,
                            'UnitPrice': 99.99,
                            'ItemRef': {'value': '300', 'name': 'Test Item'},
                        },
                    },
                    {
                        'DetailType': 'SubTotalLineDetail',
                        'Amount': 199.98,
                    },
                ],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T12:00:00Z',
                },
            },
        }

    def _make_qb_bill(self, qb_id='500', vendor_id='200'):
        return {
            'Bill': {
                'Id': qb_id,
                'SyncToken': '0',
                'VendorRef': {'value': vendor_id, 'name': 'Test Vendor'},
                'TxnDate': '2026-01-15',
                'DueDate': '2026-02-15',
                'DocNumber': 'BILL-001',
                'TotalAmt': 500.00,
                'Line': [
                    {
                        'DetailType': 'ItemBasedExpenseLineDetail',
                        'Amount': 500.00,
                        'Description': 'Purchased items',
                        'ItemBasedExpenseLineDetail': {
                            'Qty': 10,
                            'UnitPrice': 50.00,
                            'ItemRef': {'value': '300', 'name': 'Test Item'},
                        },
                    },
                ],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T12:00:00Z',
                },
            },
        }

    def _make_qb_payment(self, qb_id='600', customer_id='100'):
        return {
            'Payment': {
                'Id': qb_id,
                'SyncToken': '0',
                'CustomerRef': {'value': customer_id, 'name': 'Test Customer'},
                'TotalAmt': 199.98,
                'TxnDate': '2026-01-20',
                'MetaData': {
                    'LastUpdatedTime': '2026-01-20T10:00:00Z',
                },
            },
        }

    def _make_qb_journal_entry(self, qb_id='700'):
        return {
            'JournalEntry': {
                'Id': qb_id,
                'SyncToken': '0',
                'TxnDate': '2026-01-15',
                'DocNumber': 'JE-001',
                'Line': [
                    {
                        'DetailType': 'JournalEntryLineDetail',
                        'Amount': 1000.00,
                        'Description': 'Debit line',
                        'JournalEntryLineDetail': {
                            'PostingType': 'Debit',
                            'AccountRef': {'value': '10', 'name': 'Cash'},
                        },
                    },
                    {
                        'DetailType': 'JournalEntryLineDetail',
                        'Amount': 1000.00,
                        'Description': 'Credit line',
                        'JournalEntryLineDetail': {
                            'PostingType': 'Credit',
                            'AccountRef': {'value': '20', 'name': 'Revenue'},
                        },
                    },
                ],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_employee(self, qb_id='800', name='John Doe'):
        return {
            'Employee': {
                'Id': qb_id,
                'SyncToken': '0',
                'GivenName': name.split()[0],
                'FamilyName': ' '.join(name.split()[1:]) or '',
                'DisplayName': name,
                'PrimaryEmailAddr': {'Address': 'john@example.com'},
                'PrimaryPhone': {'FreeFormNumber': '555-8888'},
                'HiredDate': '2025-01-01',
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_department(self, qb_id='900', name='Engineering'):
        return {
            'Department': {
                'Id': qb_id,
                'SyncToken': '0',
                'Name': name,
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_time_activity(self, qb_id='1000', hours=2, minutes=30):
        return {
            'TimeActivity': {
                'Id': qb_id,
                'SyncToken': '0',
                'TxnDate': '2026-01-15',
                'NameOf': 'Employee',
                'Hours': hours,
                'Minutes': minutes,
                'Description': 'Test time activity',
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_sales_receipt(self, qb_id='1100'):
        return {
            'SalesReceipt': {
                'Id': qb_id,
                'SyncToken': '0',
                'TxnDate': '2026-01-15',
                'TotalAmt': 150.00,
                'Line': [],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_purchase_order(self, qb_id='1200', vendor_id='200'):
        return {
            'PurchaseOrder': {
                'Id': qb_id,
                'SyncToken': '0',
                'VendorRef': {'value': vendor_id},
                'TxnDate': '2026-01-15',
                'TotalAmt': 1000.00,
                'Line': [],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_deposit(self, qb_id='1300'):
        return {
            'Deposit': {
                'Id': qb_id,
                'SyncToken': '0',
                'TxnDate': '2026-01-15',
                'TotalAmt': 5000.00,
                'Line': [],
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_transfer(self, qb_id='1400'):
        return {
            'Transfer': {
                'Id': qb_id,
                'SyncToken': '0',
                'TxnDate': '2026-01-15',
                'Amount': 2000.00,
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_term(self, qb_id='1500', name='Net 30'):
        return {
            'Term': {
                'Id': qb_id,
                'SyncToken': '0',
                'Name': name,
                'DueDays': 30,
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_qb_class(self, qb_id='1600', name='Marketing'):
        return {
            'Class': {
                'Id': qb_id,
                'SyncToken': '0',
                'Name': name,
                'MetaData': {
                    'LastUpdatedTime': '2026-01-15T10:00:00Z',
                },
            },
        }

    def _make_cloud_event(self, event_type, entity_id, realm_id=None):
        """Create a CloudEvents-format webhook event."""
        return {
            'specversion': '1.0',
            'id': 'test-event-id-001',
            'source': 'intuit.test',
            'type': event_type,
            'datacontenttype': 'application/json',
            'time': '2026-01-15T12:00:00Z',
            'intuitentityid': entity_id,
            'intuitaccountid': realm_id or self.config.realm_id,
            'data': {},
        }

    def _make_legacy_webhook(self, entity_name, entity_id, operation='Update', realm_id=None):
        """Create a legacy-format webhook payload."""
        return {
            'eventNotifications': [{
                'realmId': realm_id or self.config.realm_id,
                'dataChangeEvent': {
                    'entities': [{
                        'id': entity_id,
                        'operation': operation,
                        'name': entity_name,
                        'lastUpdated': '2026-01-15T12:00:00Z',
                    }],
                },
            }],
        }
