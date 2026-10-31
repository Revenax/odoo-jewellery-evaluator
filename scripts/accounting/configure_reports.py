# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Marjaan's own Profit & Loss and Balance Sheet (idempotent).

Run through the Odoo shell (dry run unless COMMIT=1):
  sudo -u odoo env COMMIT=1 bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < configure_reports.py'

Both are variants of Odoo's own reports (Accounting > Reporting > Profit and
Loss / Balance Sheet, "Marjaan" in the report selector), so they keep the
date filter, period comparison, journal filter, PDF/XLSX export and drill
down to the journal items. Lines follow the chart of accounts by karat:

- P&L: gold metal sales by karat, making fees by kind, diamond and silver
  sales, cost of goods sold by karat, gross profit, metal price revaluation,
  operating expenses (one line per expense account, filled as expenses are
  entered), cash differences, net profit.
- Balance sheet: cash and vaults, receivables, gold in stock by karat,
  diamond and silver stock, liabilities, owners' capital and current
  accounts, profit to date; total assets must equal liabilities + equity.

Each run rebuilds the lines of both reports from the definitions below.
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
Report = env['account.report'].sudo()


def build(name, root_xmlid, scope, lines):
    root = env.ref(root_xmlid)
    report = Report.search([('name', '=', name), ('root_report_id', '=', root.id)], limit=1)
    vals = {
        'name': name,
        'root_report_id': root.id,
        'filter_date_range': root.filter_date_range,
        'filter_period_comparison': True,
        'filter_journals': True,
        'filter_unfold_all': True,
        'default_opening_date_filter': root.default_opening_date_filter,
        'column_ids': [(5, 0, 0), (0, 0, {'name': 'Balance', 'expression_label': 'balance'})],
    }
    hide = Report._fields.get('filter_hide_0_lines')
    if hide is not None:
        vals['filter_hide_0_lines'] = 'by_default' if hide.type == 'selection' else True
    if report:
        report.line_ids.unlink()
        report.write(vals)
    else:
        report = Report.create(vals)

    # Odoo orders every line of a report by sequence, so number them depth-first.
    seq = iter(range(10, 10000, 10))

    def add(defs, parent=None, level=0):
        for code, label, kind, formula, children, extra in defs:
            line = env['account.report.line'].create({
                'report_id': report.id,
                'parent_id': parent.id if parent else False,
                'name': label,
                'code': code,
                'sequence': next(seq),
                'hierarchy_level': level * 2 + (1 if formula and kind == 'codes' else 0),
                'foldable': bool(extra.get('groupby')),
                'groupby': extra.get('groupby') or False,
                'hide_if_zero': extra.get('hide_if_zero', False),
            })
            if formula:
                env['account.report.expression'].create({
                    'report_line_id': line.id,
                    'label': 'balance',
                    'engine': 'account_codes' if kind == 'codes' else 'aggregation',
                    'formula': formula,
                    'date_scope': scope,
                })
            add(children, line, level + 1)
    add(lines)
    print('REPORT', name, 'lines', len(report.line_ids))
    return report


def codes(code, label, formula, **extra):
    return (code, label, 'codes', formula, [], extra)


def total(code, label, formula, children=(), **extra):
    return (code, label, 'aggregation', formula, list(children), extra)


BY_ACCOUNT = {'groupby': 'account_id'}

PL = [
    total('MJ_REV', 'Revenue', 'MJ_RGOLD.balance + MJ_RFEE.balance + MJ_RDIA.balance + MJ_RSIL.balance + MJ_ROTH.balance', [
        total('MJ_RGOLD', 'Gold sales (metal value)', 'MJ_RG24.balance + MJ_RG21.balance + MJ_RG18.balance', [
            codes('MJ_RG24', 'Gold 24K', '-500111'),
            codes('MJ_RG21', 'Gold 21K', '-500112'),
            codes('MJ_RG18', 'Gold 18K', '-500113'),
        ]),
        total('MJ_RFEE', 'Making fees', 'MJ_RFJ.balance + MJ_RFB.balance + MJ_RFS.balance', [
            codes('MJ_RFJ', 'Gold jewellery', '-500121'),
            codes('MJ_RFB', 'Gold bullion (premium)', '-500122'),
            codes('MJ_RFS', 'Silver', '-500123'),
        ]),
        codes('MJ_RDIA', 'Diamond sales', '-500104'),
        codes('MJ_RSIL', 'Silver sales (metal value)', '-500105'),
        codes('MJ_ROTH', 'Other sales', '-500001 - 500103 - 500106', hide_if_zero=True),
    ]),
    total('MJ_COS', 'Cost of goods sold', 'MJ_CG24.balance + MJ_CG21.balance + MJ_CG18.balance + MJ_CDIA.balance + MJ_CSIL.balance + MJ_COTH.balance', [
        codes('MJ_CG24', 'Gold 24K', '400211'),
        codes('MJ_CG21', 'Gold 21K', '400212'),
        codes('MJ_CG18', 'Gold 18K', '400213'),
        codes('MJ_CDIA', 'Diamond', '400202'),
        codes('MJ_CSIL', 'Silver', '400203'),
        codes('MJ_COTH', 'Gold, karat not set', '400201 + 400204', hide_if_zero=True),
    ]),
    total('MJ_GP', 'Gross profit', 'MJ_REV.balance - MJ_COS.balance', [
        total('MJ_GPG', 'Gold (making fees)', 'MJ_RGOLD.balance + MJ_RFJ.balance + MJ_RFB.balance - MJ_CG24.balance - MJ_CG21.balance - MJ_CG18.balance - MJ_COTH.balance + MJ_ROTH.balance'),
        total('MJ_GPD', 'Diamond', 'MJ_RDIA.balance - MJ_CDIA.balance'),
        total('MJ_GPS', 'Silver', 'MJ_RSIL.balance + MJ_RFS.balance - MJ_CSIL.balance'),
    ]),
    codes('MJ_REVAL', 'Metal price revaluation (stock re-marked to today\'s price)', '-500102'),
    codes('MJ_OPEX', 'Operating expenses', '4000 + 4001', **BY_ACCOUNT),
    codes('MJ_OINC', 'Other income', '-5000\\(500001)', hide_if_zero=True, **BY_ACCOUNT),
    codes('MJ_CASHD', 'Cash differences (shift counts)', '999001 + 999002', **BY_ACCOUNT),
    total('MJ_NET', 'Net profit', 'MJ_GP.balance + MJ_REVAL.balance + MJ_OINC.balance - MJ_OPEX.balance - MJ_CASHD.balance'),
]

BS = [
    total('MJ_TA', 'Total assets', 'MJ_CASH.balance + MJ_REC.balance + MJ_STOCK.balance + MJ_OTHA.balance', [
        codes('MJ_CASH', 'Cash, vaults and bank', '101 + 105', **BY_ACCOUNT),
        codes('MJ_REC', 'Receivables', '102', **BY_ACCOUNT),
        total('MJ_STOCK', 'Stock', 'MJ_GOLD.balance + MJ_SDIA.balance + MJ_SSIL.balance', [
            total('MJ_GOLD', 'Gold in stock', 'MJ_S24.balance + MJ_S21.balance + MJ_S18.balance + MJ_SNS.balance', [
                codes('MJ_S24', 'Gold 24K', '132111'),
                codes('MJ_S21', 'Gold 21K', '132112'),
                codes('MJ_S18', 'Gold 18K', '132113'),
                codes('MJ_SNS', 'Gold, karat not set', '132101', hide_if_zero=True),
            ]),
            codes('MJ_SDIA', 'Diamond', '132102'),
            codes('MJ_SSIL', 'Silver', '132103'),
        ]),
        codes('MJ_OTHA', 'Other assets (prepayments, deposits, fixed assets)', '100 + 104 + 106', hide_if_zero=True, **BY_ACCOUNT),
    ]),
    codes('MJ_LIAB', 'Liabilities', '-2', **BY_ACCOUNT),
    total('MJ_EQ', 'Equity', 'MJ_CAP.balance + MJ_RES.balance + MJ_OWN.balance + MJ_PROFIT.balance', [
        codes('MJ_CAP', "Owners' capital", '-300001'),
        codes('MJ_RES', 'Legal reserve', '-300002', hide_if_zero=True),
        codes('MJ_OWN', "Owners' current accounts (taken out = negative)", '-3001', **BY_ACCOUNT),
        codes('MJ_PROFIT', 'Profit to date', '-4 - 5 - 9'),
    ]),
    total('MJ_LE', 'Total liabilities and equity', 'MJ_LIAB.balance + MJ_EQ.balance'),
]

pl = build('Marjaan Profit & Loss', 'account_reports.profit_and_loss', 'strict_range', PL)
bs = build('Marjaan Balance Sheet', 'account_reports.balance_sheet', 'from_beginning', BS)

# Print both for the whole year so far, as a check.
for report in (pl, bs):
    options = report.get_options({'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31',
                                           'filter': 'custom', 'mode': 'range' if report == pl else 'single'},
                                  'unfold_all': False})
    for line in report._get_lines(options):
        value = line['columns'][0].get('no_format') if line.get('columns') else ''
        print('LINE', report.name[8:], '  ' * line.get('level', 0) + line['name'], '|',
              f'{value:,.2f}' if isinstance(value, (int, float)) else value)

if COMMIT:
    env.cr.commit()
    print('REPORT done')
else:
    env.cr.rollback()
    print('REPORT dry run, rolled back')
