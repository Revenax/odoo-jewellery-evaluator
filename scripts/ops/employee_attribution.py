# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
#
# Give every hr.employee an ARCHIVED Odoo user (no login possible, no seat), then
# re-point the history of ops-app pieces at the employee who really did the work.
# The ops app syncs over XML-RPC as one user (id 2), so Odoo showed that user as
# creator of every piece and buy-back PO. Source of truth = ops DB (Neon):
# products.registered_by (creator) and approved edit change_requests (editor).
#
#   creator  -> product.template/product.product/jewellery.stone create_uid,
#               the "created" chatter note + creation-sync tracking (<=10 min),
#               buy-back PO (origin = SKU) create_uid/write_uid/user_id + its chatter
#   editor   -> chatter tracking within 5 min of the approval, product write_uid
# Bulk re-syncs (13/15/25 Jun) stay on the sync user: no person did those.
# Data block ATTRIB is generated from Neon (registered_by + approved edits).
# Rolls back unless COMMIT=1.
import json
import os
from datetime import datetime, timedelta

ATTRIB = json.loads(r'''__ATTRIB__''')
SYNC_UID, SYNC_PARTNER = 2, 3
# ops username -> hr.employee id (mohamed-a-abdallah IS user 2; ziad-zaza has no pieces)
OPS_TO_EMP = {
    'ahmed-tarek': 3, 'ahmed-fathy': 10, 'abelrazak': 13, 'omar-hashim': 4,
    'mohamed-ashraf': 12, 'omar-abbassi': 6, 'anas-abbassi': 7, 'mohamed-abbassi': 8,
}
cr = env.cr
internal = env.ref('base.group_user')
Users = env['res.users'].with_context(active_test=False, no_reset_password=True)

# 1. archived user per employee without one. It gets its OWN contact: Odoo archives a
#    user's contact with the user, and the employee's work contact must stay active.
emp_user = {}
for e in env['hr.employee'].with_context(active_test=False).search([]):
    if e.user_id:
        emp_user[e.id] = e.user_id
        continue
    login = e.name.strip().lower().replace(' ', '.') + '@marjaanjewellery.com'
    u = Users.search([('login', '=', login)], limit=1)
    if not u:
        vals = {'name': e.name, 'login': login}
        vals['group_ids' if 'group_ids' in Users._fields else 'groups_id'] = [(6, 0, [internal.id])]
        u = Users.create(vals)
        u.active = False  # create(active=False) trips Odoo's own contact check
    # SQL, not ORM: hr's _sync_user would swap the employee's work contact/image
    cr.execute('UPDATE hr_employee SET user_id=%s WHERE id=%s', (u.id, e.id))
    emp_user[e.id] = u
    print('user', u.id, u.login, 'active', u.active, 'partner', u.partner_id.id, '-> employee', e.id, e.name)

def who(ops):
    if ops == 'mohamed-a-abdallah':
        return None  # already user 2
    emp = OPS_TO_EMP.get(ops)
    return emp_user[emp] if emp else None

# 2. products, stones, creation chatter
n = {'tmpl': 0, 'stone': 0, 'msg_create': 0, 'po': 0, 'po_msg': 0, 'msg_edit': 0, 'write_uid': 0}
cr.execute('SELECT id, default_code, create_date FROM product_template WHERE create_uid=%s AND default_code = ANY(%s)',
           (SYNC_UID, list(ATTRIB['reg'])))
for tid, sku, cdate in cr.fetchall():
    u = who(ATTRIB['reg'][sku])
    if not u:
        continue
    cr.execute('UPDATE product_template SET create_uid=%s, write_uid=CASE WHEN write_uid=%s THEN %s ELSE write_uid END WHERE id=%s',
               (u.id, SYNC_UID, u.id, tid)); n['tmpl'] += 1
    cr.execute('UPDATE product_product SET create_uid=%s WHERE product_tmpl_id=%s AND create_uid=%s', (u.id, tid, SYNC_UID))
    cr.execute('UPDATE jewellery_stone SET create_uid=%s WHERE product_tmpl_id=%s AND create_uid=%s', (u.id, tid, SYNC_UID)); n['stone'] += cr.rowcount
    cr.execute("""UPDATE mail_message SET author_id=%s, create_uid=%s, write_uid=%s
                  WHERE model='product.template' AND res_id=%s AND author_id=%s AND create_date <= %s""",
               (u.partner_id.id, u.id, u.id, tid, SYNC_PARTNER, cdate + timedelta(minutes=10))); n['msg_create'] += cr.rowcount

# 3. buy-back POs (one per SKU, origin = SKU)
cr.execute('SELECT id, name, origin FROM purchase_order WHERE create_uid=%s AND origin = ANY(%s)', (SYNC_UID, list(ATTRIB['reg'])))
for pid, name, sku in cr.fetchall():
    u = who(ATTRIB['reg'][sku])
    if not u:
        continue
    cr.execute('UPDATE purchase_order SET create_uid=%s, write_uid=%s, user_id=%s WHERE id=%s', (u.id, u.id, u.id, pid)); n['po'] += 1
    cr.execute("""UPDATE mail_message SET author_id=%s, create_uid=%s, write_uid=%s
                  WHERE model='purchase.order' AND res_id=%s AND author_id=%s""", (u.partner_id.id, u.id, u.id, pid, SYNC_PARTNER))
    n['po_msg'] += cr.rowcount
    print('po', name, sku, '->', u.name)

# 4. approved edits: sync chatter within 5 min after approval -> requester; last edit -> write_uid
last = {}
for sku, ops, decided in ATTRIB['edits']:
    u = who(ops)
    if not u:
        continue
    t = datetime.fromisoformat(decided.replace('Z', '+00:00')).replace(tzinfo=None)
    cr.execute("""UPDATE mail_message m SET author_id=%s, create_uid=%s, write_uid=%s FROM product_template p
                  WHERE m.model='product.template' AND m.res_id=p.id AND p.default_code=%s AND m.author_id=%s
                    AND m.create_date BETWEEN %s AND %s""",
               (u.partner_id.id, u.id, u.id, sku, SYNC_PARTNER, t - timedelta(minutes=1), t + timedelta(minutes=5)))
    n['msg_edit'] += cr.rowcount
    print('edit', sku, ops, decided, 'messages', cr.rowcount)
    last[sku] = u
for sku, u in last.items():
    cr.execute('UPDATE product_template SET write_uid=%s WHERE default_code=%s', (u.id, sku)); n['write_uid'] += cr.rowcount

cr.execute("""SELECT u.login, count(*) FROM product_template p JOIN res_users u ON u.id=p.create_uid GROUP BY 1 ORDER BY 2 DESC""")
print('creators now', cr.fetchall())
print(n)
if os.environ.get('COMMIT') == '1':
    env.cr.commit(); print('COMMITTED')
else:
    env.cr.rollback(); print('DRY RUN (rolled back)')
