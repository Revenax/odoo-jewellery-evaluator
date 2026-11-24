# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Finish a full stock count (jewellery.stock.take) for the owner.

TAKE=ST/0004  APPROVER="Mohamed A. Abdallah"  [APPROVER_LOGIN=<login>]  UNDECIDED=lost  [COMMIT=1]
APPROVER_LOGIN creates the approver employee, linked to that admin login,
when there is none.
Every missing piece still without a decision gets UNDECIDED, then each open
mini count is approved with the approver's badge (same path as the scan
screen: action_approve applies every decision and posts its entries).
Rolls back unless COMMIT=1.
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
take = env['jewellery.stock.take'].search([('name', '=', os.environ.get('TAKE', 'ST/0004'))])
assert len(take) == 1, 'stock take not found'
approver = os.environ.get('APPROVER', 'Mohamed A. Abdallah')
employee = env['hr.employee'].search([('name', '=', approver)])
if not employee and os.environ.get('APPROVER_LOGIN'):
    # Owner-approved (2026-11-24): an employee for an admin login that has
    # none, with a random badge that is never printed.
    import secrets
    user = env['res.users'].search([('login', '=', os.environ['APPROVER_LOGIN'])])
    assert len(user) == 1, 'APPROVER_LOGIN not found'
    employee = env['hr.employee'].search([('user_id', '=', user.id)])
    if employee:
        # The login's own employee (it was named after the company): rename it.
        print('EMPLOYEE RENAMED', employee.id, employee.name, '->', approver)
        employee.name = approver
        if not employee.barcode:
            employee.barcode = str(secrets.randbelow(9 * 10**11) + 10**11)
    else:
        employee = env['hr.employee'].create({'name': approver, 'user_id': user.id,
                                              'barcode': str(secrets.randbelow(9 * 10**11) + 10**11)})
        print('EMPLOYEE CREATED', employee.id, employee.name, 'linked to', user.login)
assert len(employee) == 1 and employee.barcode, f'approver: {employee.mapped("name")} (needs one employee with a badge)'
Count = env['jewellery.stock.count']
assert Count._badge_admin(employee.barcode) == employee, f'{employee.name} is not an admin'
undecided = os.environ.get('UNDECIDED', 'lost')
print('TAKE', take.name, take.state, 'minis', take.mini_done, '/', take.mini_total)
minis = take.count_ids
for mini in minis.filtered(lambda c: c.state != 'done'):
    lines = mini.line_ids.filtered(lambda l: l.status == 'to_find' and not l.resolution)
    for line in lines:
        print('  DECIDE', mini.name, line.default_code, undecided)
        line.resolution = undecided
    decided = mini.line_ids.filtered(lambda l: l.status == 'to_find')
    print('MINI', mini.name, mini.state, 'found', mini.found_count, 'missing', mini.missing_count,
          'decisions', sorted(set(decided.mapped('resolution'))))
    mini.action_approve(employee.barcode)
    print('  APPROVED', mini.name, mini.state, 'entries', mini.adjustment_move_ids.mapped('name'))
take.invalidate_recordset()
print('TAKE', take.name, take.state, 'minis', take.mini_done, '/', take.mini_total)
if COMMIT:
    env.cr.commit()
    print('COMMITTED')
else:
    env.cr.rollback()
    print('ROLLED BACK (dry run)')
