# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Accounting setup for Marjaan (idempotent). Configuration only, no entries.

Run through the Odoo shell (dry run unless COMMIT=1):
  sudo -u odoo env COMMIT=1 bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < configure_accounting.py'

What it sets up:
- Per-material accounts: sales, cost of goods sold and inventory for Gold,
  Diamond and Silver, a metal-price revaluation account (where the nightly
  re-mark lands), and Owners' Capital (counterpart of the opening stock).
- Jewellery categories on perpetual (real-time) valuation at standard cost,
  pointed at those accounts. models/inventory_costing.py keeps the cost at
  today's metal price. Non-jewellery categories stay periodic.
- No taxes: Marjaan charges none. Every tax is archived and removed from
  products and company defaults.
- Branch Vaults: Ismail Ramzy, Black Closet and Abbassi Sagha each get a
  "Vault - <branch>" cash journal posting straight to its own cash account,
  a Cash payment method, the shared InstaPay method, and their own
  warehouse's PoS picking type (they used Sway Mall's, so a branch sale
  would have taken Sway Mall stock).
- Today's USD/SAR/AED rates from the price feed (SAR/AED were 1.0).
- The duplicate "Gold / Coin" category merged into the one in use.
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
LOG = []


def log(msg):
    LOG.append(msg)
    print('ACCT', msg)


company = env.company
Account = env['account.account'].sudo()


def account(code, name, account_type, **extra):
    acc = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if acc and acc.name != name:
        raise ValueError(f'account code {code} is already used by "{acc.name}"; pick another code')
    if not acc:
        acc = Account.create({'code': code, 'name': name, 'account_type': account_type,
                              'company_ids': [(6, 0, company.ids)], **extra})
        log(f'account {code} {name} created')
    else:
        diff = {k: v for k, v in extra.items() if acc[k].id != v}
        if diff:
            acc.write(diff)
            log(f'account {code} updated: {sorted(diff)}')
    return acc


# ── accounts ────────────────────────────────────────────────────────────
revaluation = account('500102', 'Metal Price Revaluation', 'income_other')
capital = account('300001', "Owners' Capital", 'equity')
MATERIALS = {}
for i, material in enumerate(('Gold', 'Diamond', 'Silver'), start=1):
    MATERIALS[material] = {
        'income': account(f'50010{2 + i}', f'Sales - {material}', 'income'),
        'cogs': account(f'40020{i}', f'Cost of Goods Sold - {material}', 'expense_direct_cost'),
        'stock': account(f'13210{i}', f'Inventory - {material}', 'asset_current',
                         account_stock_variation_id=revaluation.id),
    }

# ── company ─────────────────────────────────────────────────────────────
wanted = {
    'anglo_saxon_accounting': True,
    'account_stock_valuation_id': MATERIALS['Gold']['stock'].id,
    # Closed by our nightly cron right after the re-mark, not by Odoo's own.
    'inventory_period': 'manual',
}
diff = {k: v for k, v in wanted.items()
        if (company[k].id if hasattr(company[k], 'id') else company[k]) != v}
if diff:
    company.write(diff)
    log(f'company updated: {sorted(diff)}')

# ── categories ──────────────────────────────────────────────────────────
Categ = env['product.category'].sudo()
coins = Categ.search([('complete_name', '=', 'Gold / Coin')], order='id')
if len(coins) > 1:
    keep = max(coins, key=lambda c: env['product.template'].with_context(active_test=False)
               .search_count([('categ_id', '=', c.id)]))
    for dup in coins - keep:
        moved = env['product.template'].with_context(active_test=False).search([('categ_id', '=', dup.id)])
        moved.write({'categ_id': keep.id})
        log(f'category Gold / Coin #{dup.id}: {len(moved)} products moved to #{keep.id}, category deleted')
        dup.unlink()

ROOTS = {'Gold': 'Gold', 'Jewellery': 'Gold', 'Diamond': 'Diamond', 'Silver': 'Silver'}
for categ in Categ.search([]):
    material = ROOTS.get(categ.complete_name.split(' / ')[0])
    if not material:
        continue
    acc = MATERIALS[material]
    vals = {
        'property_valuation': 'real_time',
        'property_cost_method': 'standard',
        'property_account_income_categ_id': acc['income'].id,
        'property_account_expense_categ_id': acc['cogs'].id,
        'property_stock_valuation_account_id': acc['stock'].id,
    }
    diff = {k: v for k, v in vals.items()
            if (categ[k].id if hasattr(categ[k], '_name') else categ[k]) != v}
    if diff:
        categ.write(diff)
        log(f'category {categ.complete_name}: {sorted(diff)}')

# ── taxes: none ─────────────────────────────────────────────────────────
Tmpl = env['product.template'].sudo().with_context(active_test=False)
for field in ('taxes_id', 'supplier_taxes_id'):
    taxed = Tmpl.search([(field, '!=', False)])
    if taxed:
        taxed.write({field: [(5, 0, 0)]})
        log(f'{len(taxed)} products: {field} cleared')
for field in ('account_sale_tax_id', 'account_purchase_tax_id'):
    if company[field]:
        company[field] = False
        log(f'company {field} cleared')
taxes = env['account.tax'].sudo().search([])
if taxes:
    taxes.write({'active': False})
    log(f'{len(taxes)} taxes archived')

# ── branch Vaults ───────────────────────────────────────────────────────
Journal = env['account.journal'].sudo()
PosMethod = env['pos.payment.method'].sudo()
instapay = PosMethod.search([('journal_id.code', '=', 'IPAY')], limit=1)
BRANCHES = [('IR', 'Ismail Ramzy', 'VIR', '105010'), ('BC', 'Black Closet', 'VBC', '105011'),
            ('AS', 'Abbassi Sagha', 'VAS', '105012')]
for wh_code, branch, jcode, acode in BRANCHES:
    warehouse = env['stock.warehouse'].sudo().search([('code', '=', wh_code)], limit=1)
    config = env['pos.config'].sudo().search([('name', '=', branch)], limit=1)
    if not warehouse or not config:
        log(f'SKIP {branch}: warehouse or POS config not found')
        continue
    cash_acc = account(acode, f'Vault - {branch}', 'asset_cash')
    journal = Journal.search([('code', '=', jcode)], limit=1)
    if not journal:
        journal = Journal.create({'name': f'Vault - {branch}', 'code': jcode, 'type': 'cash',
                                  'default_account_id': cash_acc.id})
        log(f'journal {jcode} Vault - {branch} created')
    # Direct posting: cash payments hit the drawer account, not Outstanding.
    for line in journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids:
        if line.payment_account_id != cash_acc:
            line.payment_account_id = cash_acc
            log(f'{jcode} payment method line {line.name}: posts straight to {acode}')
    method = PosMethod.search([('journal_id', '=', journal.id)], limit=1)
    if not method:
        method = PosMethod.create({'name': f'Cash {branch}', 'journal_id': journal.id,
                                   'company_id': company.id})
        log(f'POS method Cash {branch} created')
    wanted_methods = method | instapay
    if wanted_methods - config.payment_method_ids:
        config.payment_method_ids = [(4, m.id) for m in wanted_methods]
        log(f'POS {branch}: Cash + InstaPay added')
    if warehouse.vault_journal_id != journal:
        warehouse.vault_journal_id = journal
        log(f'warehouse {wh_code}: vault = {jcode}')
    if warehouse.pos_type_id and config.picking_type_id != warehouse.pos_type_id:
        config.picking_type_id = warehouse.pos_type_id
        log(f'POS {branch}: ships from its own warehouse {wh_code}')

# ── currency rates ──────────────────────────────────────────────────────
env['product.template']._update_currency_rates()
for code in ('USD', 'SAR', 'AED'):
    cur = env['res.currency'].search([('name', '=', code)], limit=1)
    if cur:
        log(f'rate {code}: 1 {code} = {1 / cur.rate:.4f} EGP')

if COMMIT:
    env.cr.commit()
    print('ACCT done,', len(LOG), 'changes')
else:
    env.cr.rollback()
    print('ACCT dry run,', len(LOG), 'changes rolled back')
