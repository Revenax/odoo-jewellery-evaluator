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
- Gold by karat (24K, 21K, 18K): inventory, metal sales and cost of gold
  sold, used for every gold piece (jewellery, bars, coins) through
  models/karat_accounts.py, plus making-fee accounts (gold jewellery, gold
  bullion premium, silver) for what a sale earns above the metal value.
  The category accounts (Gold / Gold Bullion "karat not set", Diamond,
  Silver) only catch what has no karat accounts.
- Chart tidy-up: the Egyptian template's unused accounts are archived
  (only accounts with no entries and no live reference; the ones a
  4-branch retailer will need are kept), owners' accounts and the legal
  reserve move to equity, gains to other income, and account groups give
  the chart and the trial balance one subtotal per section.
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
LOG = []


def log(msg):
    LOG.append(msg)
    print('ACCT', msg)


company = env.company
Account = env['account.account'].sudo()


def account(code, name, account_type, old_names=(), **extra):
    acc = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if acc and acc.name != name and acc.name in old_names:
        log(f'account {code} renamed "{acc.name}" -> "{name}"')
        acc.name = name
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
from odoo.addons.jewellery_evaluator.jewellery_evaluator.utils import (
    GOLD_KARAT_ACCOUNTS, MAKING_FEE_ACCOUNTS, SILVER_ACCOUNTS)

# Category accounts. Gold and silver pieces are booked on their karat's
# accounts below (models/karat_accounts.py); these only catch a gold piece
# whose karat is not set. Diamonds and center stones stay on Diamond.
MATERIALS = {
    'Gold': {
        'income': account('500103', 'Sales - Gold (karat not set)', 'income',
                          old_names=('Sales - Gold', 'Sales - Gold Jewellery')),
        'cogs': account('400201', 'Cost of Gold Sold - karat not set', 'expense_direct_cost',
                        old_names=('Cost of Goods Sold - Gold', 'Cost of Goods Sold - Gold Jewellery')),
        'stock': account('132101', 'Inventory - Gold (karat not set)', 'asset_current',
                         old_names=('Inventory - Gold',), account_stock_variation_id=revaluation.id),
    },
    'Diamond': {
        'income': account('500104', 'Sales - Diamond', 'income'),
        'cogs': account('400202', 'Cost of Goods Sold - Diamond', 'expense_direct_cost'),
        'stock': account('132102', 'Inventory - Diamond', 'asset_current',
                         account_stock_variation_id=revaluation.id),
    },
    'Silver': {
        'income': account(SILVER_ACCOUNTS['income'], 'Sales - Silver (metal value)', 'income',
                          old_names=('Sales - Silver',)),
        'cogs': account(SILVER_ACCOUNTS['expense'], 'Cost of Silver Sold', 'expense_direct_cost',
                        old_names=('Cost of Goods Sold - Silver',)),
        'stock': account(SILVER_ACCOUNTS['stock'], 'Inventory - Silver', 'asset_current',
                         account_stock_variation_id=revaluation.id),
    },
}
MATERIALS['Bullion'] = {
    'income': account('500106', 'Sales - Gold Bullion (karat not set)', 'income',
                      old_names=('Sales - Gold Bullion',)),
    'cogs': account('400204', 'Cost of Gold Bullion Sold - karat not set', 'expense_direct_cost',
                    old_names=('Cost of Goods Sold - Gold Bullion',)),
    'stock': MATERIALS['Gold']['stock'],
}

# Gold by karat: what is in stock, metal sales, cost of gold sold.
for karat, codes in GOLD_KARAT_ACCOUNTS.items():
    account(codes['stock'], f'Inventory - Gold {karat}', 'asset_current',
            account_stock_variation_id=revaluation.id)
    account(codes['income'], f'Sales - Gold {karat} (metal value)', 'income')
    account(codes['expense'], f'Cost of Gold Sold - {karat}', 'expense_direct_cost')
# What the customer pays above the metal value.
FEE_NAMES = {'500121': 'Making Fee - Gold Jewellery', '500122': 'Making Fee - Gold Bullion (premium)',
             '500123': 'Making Fee - Silver'}
for code in sorted(set(MAKING_FEE_ACCOUNTS.values())):
    account(code, FEE_NAMES[code], 'income')
KARAT_CODES = {c for codes in GOLD_KARAT_ACCOUNTS.values() for c in codes.values()} \
    | set(SILVER_ACCOUNTS.values()) | set(MAKING_FEE_ACCOUNTS.values())

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
BULLION = ('Gold / Bar', 'Gold / Coin', 'Gold / Ingot')
for categ in Categ.search([]):
    material = ROOTS.get(categ.complete_name.split(' / ')[0])
    if any(categ.complete_name == b or categ.complete_name.startswith(b + ' / ') for b in BULLION):
        material = 'Bullion'
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

# ── chart tidy-up ───────────────────────────────────────────────────────
# Owners' accounts are what each owner took out of (or put into) the
# Vaults: equity, not cash. Their journals stay cash journals named
# "Owner - ..." (that is how the POS cash-ops find them).
RECODES = {
    '105006': ('300101', 'Owner Current Account - Anas Abbassi', 'equity'),
    '105007': ('300102', 'Owner Current Account - Omar Abbassi', 'equity'),
    '105008': ('300103', 'Owner Current Account - Mohamed Abbassi', 'equity'),
    '105009': ('300104', 'Owner Current Account - Ahmed Abbassi', 'equity'),
    '201021': ('300002', 'Legal Reserve', 'equity'),
}
for old, (new, name, account_type) in RECODES.items():
    acc = Account.search([('code', '=', old), ('company_ids', 'in', company.id)], limit=1)
    if acc:
        acc.write({'code': new, 'name': name, 'account_type': account_type})
        log(f'account {old} -> {new} {name} ({account_type})')

# Sales from free-text invoice lines (no product) and non-jewellery products.
RENAMES = {'500001': 'Sales - Other'}
for code, name in RENAMES.items():
    acc = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if acc and acc.name != name:
        log(f'account {code} renamed "{acc.name}" -> "{name}"')
        acc.name = name

TYPES = {'500009': 'income_other', '500010': 'income_other', '500011': 'income_other',
         '500013': 'income_other', '999002': 'income_other',
         '106001': 'asset_non_current', '106006': 'asset_non_current'}
for code, account_type in TYPES.items():
    acc = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if acc and acc.account_type != account_type:
        log(f'account {code} {acc.name}: {acc.account_type} -> {account_type}')
        acc.account_type = account_type

# The template pointed deferred expenses at a duplicate "Outstanding
# Receipts" and deferred revenue at "Credit Notes to Customers".
for field, code in (('deferred_expense_account_id', '104035'), ('deferred_revenue_account_id', '201018')):
    acc = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if acc and company[field] != acc:
        company[field] = acc
        log(f'company {field} -> {code} {acc.name}')

# Unused journals from the template.
for code in ('BNK1', 'IFRS'):
    journal = env['account.journal'].sudo().search([('code', '=', code)], limit=1)
    if journal and not env['account.move'].sudo().search_count([('journal_id', '=', journal.id)]):
        journal.active = False
        log(f'journal {code} {journal.name} archived (never used)')

# Unused template accounts are archived; archiving is reversible and keeps
# them out of every list and report. Never archived: an account with an
# entry, one a live record points at (journals, company defaults,
# categories, payment methods, payroll rules, asset models...), and the
# ones below that a 4-branch jeweller will use.
KEEP = {
    '100001', '101002', '101003', '101008', '102014', '104023', '104035', '104037', '104040',
    '106001', '106002', '106003', '106004', '106006', '106007', '106008', '106009', '132103',
    '201001', '201002', '201004', '201007', '201011', '201015', '201016', '201018', '202001',
    '300002', '999999',
    '400003', '400011', '400012', '400015', '400016', '400018', '400020', '400021', '400022',
    '400028', '400029', '400031', '400032', '400034', '400036', '400040', '400042', '400043',
    '400044', '400045', '400046', '400047', '400048', '400050', '400051', '400058', '400067',
    '400086', '400088', '400089',
    '500001', '500013', '500102', '500104', '500105', '500106', '400202', '400203', '400204',
} | KARAT_CODES
# Zero-balance accounts with old entries that no longer mean anything (no taxes).
RETIRE = {'100103'}
# References that do not keep an account alive: the archived taxes.
DEAD_REFS = {'account.tax.repartition.line', 'account.tax.group'}
env.flush_all()
live = set()
for mname, model in env.registry.items():
    if model._abstract or not model._auto or mname in ('account.move.line', 'account.account') + tuple(DEAD_REFS):
        continue
    for fname, f in model._fields.items():
        if f.comodel_name != 'account.account' or not f.store and not f.company_dependent:
            continue
        where = ' AND active' if mname == 'account.journal' else ''
        if f.company_dependent:
            env.cr.execute(f'SELECT DISTINCT (jsonb_each_text("{fname}")).value FROM "{model._table}" WHERE "{fname}" IS NOT NULL')
            live |= {int(v) for (v,) in env.cr.fetchall() if v}
        elif f.type == 'many2one':
            env.cr.execute(f'SELECT DISTINCT "{fname}" FROM "{model._table}" WHERE "{fname}" IS NOT NULL{where}')
            live |= {v for (v,) in env.cr.fetchall()}
        elif f.type == 'many2many':
            env.cr.execute(f'SELECT DISTINCT "{f.column2}" FROM "{f.relation}"')
            live |= {v for (v,) in env.cr.fetchall()}
env.cr.execute("""SELECT account_id, COUNT(*), COALESCE(SUM(balance), 0) FROM account_move_line
                   WHERE parent_state = 'posted' GROUP BY account_id""")
used = {aid: (n, bal) for aid, n, bal in env.cr.fetchall()}
archived = []
for acc in Account.search([('company_ids', 'in', company.id)]):
    n, bal = used.get(acc.id, (0, 0))
    if acc.code in KEEP or acc.id in live:
        continue
    if n and not (acc.code in RETIRE and company.currency_id.is_zero(bal)):
        continue
    acc.active = False
    archived.append(acc.code)
if archived:
    log(f'{len(archived)} unused accounts archived: {", ".join(sorted(archived))}')

# Account groups: the chart and the trial balance get one subtotal per
# section. Odoo files each account under the narrowest matching prefix.
GROUPS = [
    ('1', '1', 'Assets'),
    ('100', '100', 'Other Current Assets'),
    ('101', '101', 'Bank & Payment Channels'),
    ('102', '102', 'Receivables'),
    ('104', '104', 'Prepayments & Deposits'),
    ('105', '105', 'Vaults (Cash)'),
    ('106', '106', 'Fixed Assets'),
    ('132', '132', 'Inventory'),
    ('13211', '13211', 'Gold in Stock by Karat'),
    ('2', '2', 'Liabilities'),
    ('201', '201', 'Current Liabilities'),
    ('202', '202', 'Non-current Liabilities'),
    ('3', '3', 'Equity'),
    ('3001', '3001', "Owners' Current Accounts"),
    ('4', '4', 'Expenses'),
    ('4000', '4001', 'Operating Expenses'),
    ('4002', '4002', 'Cost of Goods Sold'),
    ('40021', '40021', 'Cost of Gold Sold by Karat'),
    ('5', '5', 'Income'),
    ('5000', '5000', 'Other Income'),
    ('5001', '5001', 'Jewellery Sales & Metal Revaluation'),
    ('50011', '50011', 'Gold Sales by Karat (metal value)'),
    ('50012', '50012', 'Making Fees'),
    ('9', '9', 'Cash Differences & Closing'),
]
Group = env['account.group'].sudo()
for start, end, name in GROUPS:
    group = Group.search([('code_prefix_start', '=', start), ('company_id', '=', company.id)], limit=1)
    if not group:
        Group.create({'name': name, 'code_prefix_start': start, 'code_prefix_end': end, 'company_id': company.id})
        log(f'account group {start} {name} created')
    elif (group.name, group.code_prefix_end) != (name, end):
        group.write({'name': name, 'code_prefix_end': end})
        log(f'account group {start} -> {name}')

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
