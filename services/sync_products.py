import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QBSyncProducts(models.AbstractModel):
    _name = 'qb.sync.products'
    _description = 'QuickBooks Product/Item Sync'

    # ---- Field Mapping ----

    def _odoo_to_qb_item(self, product):
        """Map Odoo product.product to QBO Item."""
        item_type = 'NonInventory'
        if product.type == 'consu':
            item_type = 'NonInventory'
        elif product.type == 'service':
            item_type = 'Service'
        elif product.type == 'product':
            item_type = 'Inventory'

        data = {
            'Name': (product.name or '')[:100],
            'Type': item_type,
            'Description': (product.description_sale or product.name or '')[:4000],
            'UnitPrice': product.list_price or 0.0,
            'PurchaseCost': product.standard_price or 0.0,
            'Sku': product.default_code or '',
            'Active': product.active,
            'Taxable': bool(product.taxes_id),
        }
        if product.categ_id:
            data['Description'] = '%s | %s' % (
                product.categ_id.complete_name, data['Description'],
            )

        if item_type == 'Inventory':
            data['TrackQtyOnHand'] = True
            data['QtyOnHand'] = product.qty_available or 0.0
            data['InvStartDate'] = fields.Date.today().isoformat()

        # Income/Expense account refs if mapped
        income_account = self._find_qb_account(product, 'income')
        if income_account:
            data['IncomeAccountRef'] = {'value': income_account}
        expense_account = self._find_qb_account(product, 'expense')
        if expense_account:
            data['ExpenseAccountRef'] = {'value': expense_account}
        asset_account = self._find_qb_account(product, 'asset')
        if asset_account and item_type == 'Inventory':
            data['AssetAccountRef'] = {'value': asset_account}

        return data

    def _qb_item_to_odoo(self, qb_data):
        """Map a QBO Item to Odoo product.product vals."""
        qb_type = qb_data.get('Type', 'NonInventory')
        odoo_type = 'consu'
        if qb_type == 'Service':
            odoo_type = 'service'
        elif qb_type == 'Inventory':
            odoo_type = 'product'

        vals = {
            'name': qb_data.get('Name', ''),
            'default_code': qb_data.get('Sku') or False,
            'list_price': qb_data.get('UnitPrice', 0.0),
            'standard_price': qb_data.get('PurchaseCost', 0.0),
            'type': odoo_type,
            'active': qb_data.get('Active', True),
            'description_sale': qb_data.get('Description', ''),
            'qb_item_id': str(qb_data.get('Id', '')),
            'qb_sync_token': str(qb_data.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        }
        return vals

    def _find_qb_account(self, product, account_type):
        """Find the QBO account ID for a product's income/expense/asset account."""
        Account = self.env['account.account']
        if account_type == 'income':
            accounts = product.property_account_income_id or (
                product.categ_id.property_account_income_categ_id
            )
        elif account_type == 'expense':
            accounts = product.property_account_expense_id or (
                product.categ_id.property_account_expense_categ_id
            )
        elif account_type == 'asset':
            accounts = product.categ_id.property_stock_valuation_account_id
        else:
            return None

        if accounts and accounts.qb_account_id:
            return accounts.qb_account_id
        return None

    # ---- Push ----

    def push(self, client, config, job):
        product = self.env['product.product'].browse(job.odoo_record_id)
        if not product.exists():
            return {}

        payload = self._odoo_to_qb_item(product)
        qb_id = product.qb_item_id

        if qb_id:
            existing = client.read('Item', qb_id)
            entity_data = existing.get('Item', {})
            payload['Id'] = qb_id
            payload['SyncToken'] = entity_data.get('SyncToken', '0')
            payload['sparse'] = True
            resp = client.update('Item', payload)
        else:
            resp = client.create('Item', payload)

        created = resp.get('Item', {})
        product.with_context(skip_qb_sync=True).write({
            'qb_item_id': str(created.get('Id', '')),
            'qb_sync_token': str(created.get('SyncToken', '')),
            'qb_last_synced': fields.Datetime.now(),
            'qb_sync_error': False,
        })
        return {'qb_id': str(created.get('Id', ''))}

    # ---- Pull ----

    def pull(self, client, config, job):
        if job.qb_entity_id:
            resp = client.read('Item', job.qb_entity_id)
            qb_data = resp.get('Item', {})
        elif job.odoo_record_id:
            product = self.env['product.product'].browse(job.odoo_record_id)
            if not product.qb_item_id:
                return {}
            resp = client.read('Item', product.qb_item_id)
            qb_data = resp.get('Item', {})
        else:
            return {}

        if not qb_data:
            return {}

        vals = self._qb_item_to_odoo(qb_data)
        qb_id = str(qb_data.get('Id', ''))

        existing = self.env['product.product'].search([
            ('qb_item_id', '=', qb_id),
        ], limit=1)

        if existing:
            resolver = self.env['qb.conflict.resolver']
            decision = resolver.resolve(config, existing, qb_data, 'product')
            if decision == 'qbo':
                existing.with_context(skip_qb_sync=True).write(vals)
            elif decision == 'conflict':
                job.write({'state': 'conflict'})
        else:
            self.env['product.product'].with_context(skip_qb_sync=True).create(vals)

        return {'qb_id': qb_id}

    # ---- Bulk ----

    def pull_all(self, client, config, entity_type):
        where = ''
        if config.last_sync_date:
            where = "MetaData.LastUpdatedTime > '%s'" % (
                config.last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            )
        records = client.query_all('Item', where_clause=where)
        Product = self.env['product.product']

        for qb_data in records:
            qb_id = str(qb_data.get('Id', ''))
            vals = self._qb_item_to_odoo(qb_data)
            existing = Product.search([('qb_item_id', '=', qb_id)], limit=1)
            if existing:
                resolver = self.env['qb.conflict.resolver']
                if resolver.resolve(config, existing, qb_data, 'product') == 'qbo':
                    existing.with_context(skip_qb_sync=True).write(vals)
            else:
                Product.with_context(skip_qb_sync=True).create(vals)

    def push_all(self, client, config, entity_type):
        products = self.env['product.product'].search([
            ('qb_item_id', '=', False),
            ('qb_do_not_sync', '=', False),
        ])
        queue = self.env['quickbooks.sync.queue']
        for product in products:
            queue.enqueue(
                entity_type='product',
                direction='push',
                operation='create',
                odoo_record_id=product.id,
                odoo_model='product.product',
                company=config.company_id,
            )
