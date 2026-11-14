# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: reverse the direction of DONE internal transfers entered the wrong way.

    scripts/ops/run_odoo.sh scripts/ops/flip_transfer.py PICKINGS=SM/INT/00020,SM/INT/00021 [FIX=1 [HOME_LOC=SM/Stock]] [COMMIT=1]

For each picking, source and destination are swapped on the picking, its moves and
move lines, and the stock quants are corrected by the difference (a done move of q
from A to B, flipped, is +2q at A and -2q at B). With FIX=1, every unique piece in
those pickings is then set to its true on-hand by inventory adjustment: 1 at HOME_LOC
(where the owner says the pieces physically are; default = where the quants are
highest), 0 elsewhere, and 0 everywhere if the piece is sold. An internal move has no accounting
effect; the adjustment nets to zero across the two locations.
"""
import os

names = [n for n in os.environ.get('PICKINGS', '').split(',') if n]
cr = env.cr
Quant = env['stock.quant'].sudo()
products = env['product.product']
for name in names:
    p = env['stock.picking'].search([('name', '=', name)])
    assert len(p) == 1 and p.state == 'done', (name, p.state)
    src, dst = p.location_id, p.location_dest_id
    done = p.move_ids.filtered(lambda m: m.state == 'done')
    for ml in done.move_line_ids:
        assert not ml.lot_id and not ml.package_id and not ml.result_package_id, ml
        q = ml.quantity
        Quant._update_available_quantity(ml.product_id, ml.location_id, 2 * q)
        Quant._update_available_quantity(ml.product_id, ml.location_dest_id, -2 * q)
    ids = {'p': p.id, 'm': tuple(p.move_ids.ids)}
    cr.execute("UPDATE stock_picking SET location_id = location_dest_id, location_dest_id = location_id WHERE id = %(p)s", ids)
    cr.execute("UPDATE stock_move SET location_id = location_dest_id, location_dest_id = location_id WHERE id IN %(m)s", ids)
    cr.execute("UPDATE stock_move_line SET location_id = location_dest_id, location_dest_id = location_id WHERE move_id IN %(m)s", ids)
    p.message_post(body=f'Direction corrected: was {src.complete_name} → {dst.complete_name}, now {dst.complete_name} → {src.complete_name} (entered the wrong way round).')
    print(name, 'flipped to', dst.complete_name, '->', src.complete_name, 'lines', len(done.move_line_ids))
    products |= done.product_id
env.invalidate_all()
if os.environ.get('FIX') == '1':
    for pr in products:
        qs = Quant.search([('product_id', '=', pr.id), ('location_id.usage', '=', 'internal')])
        total = sum(qs.mapped('quantity'))
        sold = bool(env['pos.order.line'].search_count([('product_id', '=', pr.id), ('qty', '>', 0)])
                    or env['account.move.line'].search_count([('product_id', '=', pr.id),
                                                              ('move_id.move_type', '=', 'out_invoice'),
                                                              ('parent_state', '=', 'posted')]))
        home_name = os.environ.get('HOME_LOC') or os.environ.get('HOME_WH')
        if sold or total <= 0:
            want = {q.location_id: 0 for q in qs}
        else:
            home = (env['stock.location'].search([('complete_name', '=', home_name)]) if home_name
                    else max(qs, key=lambda q: q.quantity).location_id)
            want = {q.location_id: 0 for q in qs}
            want[home] = 1
        for loc, qty in want.items():
            q = qs.filtered(lambda x, loc=loc: x.location_id == loc)
            if not q:
                q = Quant.create({'product_id': pr.id, 'location_id': loc.id, 'quantity': 0})
            if q.quantity != qty:
                q.with_context(inventory_mode=True).inventory_quantity = qty
                q.with_context(inventory_name='Correction of wrong-way transfers %s' % ', '.join(names)).action_apply_inventory()
                print('  adjusted', pr.default_code, loc.complete_name, '->', qty)
env.invalidate_all()
bad = []
for pr in products:
    qs = Quant.search([('product_id', '=', pr.id), ('location_id.usage', '=', 'internal'), ('quantity', '!=', 0)])
    state = [(q.location_id.complete_name, q.quantity) for q in qs]
    if state not in ([('SM/Stock', 1.0)], []):
        bad.append((pr.default_code, state))
print('pieces', len(products), 'not exactly 1 in SM (or 0 if sold):', bad)
if os.environ.get('COMMIT') == '1':
    cr.commit(); print('COMMITTED')
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')
