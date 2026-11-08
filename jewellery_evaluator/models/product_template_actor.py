# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Credit the real employee for what the ops app syncs.

The ops app talks to Odoo over XML-RPC as ONE user, so without this every piece,
stone, buy-back PO and their chatter would show that sync user. The ops app now
passes the person in the call context: ``{'jewellery_actor': '<ops login>'}``
(the registrant on create, the requester on an approved edit). The login maps to
an Odoo user through ``res.users.jewellery_ops_login`` (every employee has an
archived user for this; archived users cannot log in and take no seat).

Just before the call's transaction commits (after Odoo's own tracking has posted
its chatter), the rows this call created or wrote are re-stamped with that user:
``create_uid``/``write_uid``, the PO Buyer, and the chatter author. Only rows
stamped with the calling user in THIS transaction are touched, so it can never
rewrite older history. An unknown login is a no-op; nothing here can fail a sync.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ACTOR_KEY = 'jewellery_actor'


class ResUsers(models.Model):
    _inherit = 'res.users'

    jewellery_ops_login = fields.Char(
        string='Operations app login',
        index=True,
        copy=False,
        help='Username in the operations app. Pieces and buy-backs this person '
             'registers or edits there are credited to this user in Odoo.',
    )

    _jewellery_ops_login_unique = models.Constraint(
        'UNIQUE(jewellery_ops_login)',
        'This operations app login is already linked to another user.',
    )


def _actor_user(env):
    """The Odoo user for the context's ops login, or None."""
    login = (env.context.get(ACTOR_KEY) or '').strip()
    if not login:
        return None
    user = env['res.users'].sudo().with_context(active_test=False).search(
        [('jewellery_ops_login', '=', login)], limit=1)
    if not user or user.id == env.uid:
        return None
    return user


def _restamp(env, user, targets):
    """Register a pre-commit re-stamp of ``targets`` for ``user``.

    targets: list of (table, model_name, ids, extra_user_columns).
    """
    caller_uid = env.uid
    caller_partner = env.user.partner_id.id
    cr = env.cr

    def run():
        try:
            env.flush_all()
            now = cr.now()
            for table, model_name, ids, extra_cols in targets:
                if not ids:
                    continue
                sets = ', '.join(
                    [f'{col} = CASE WHEN {col} = %(caller)s THEN %(actor)s ELSE {col} END'
                     for col in ('create_uid', 'write_uid', *extra_cols)])
                cr.execute(
                    f'UPDATE {table} SET {sets} WHERE id = ANY(%(ids)s) AND write_date >= %(now)s',
                    {'caller': caller_uid, 'actor': user.id, 'ids': list(ids), 'now': now})
                cr.execute(
                    """UPDATE mail_message
                          SET author_id = %(partner)s, create_uid = %(actor)s, write_uid = %(actor)s
                        WHERE model = %(model)s AND res_id = ANY(%(ids)s)
                          AND author_id = %(caller_partner)s AND create_date >= %(now)s""",
                    {'partner': user.partner_id.id, 'actor': user.id, 'model': model_name,
                     'ids': list(ids), 'caller_partner': caller_partner, 'now': now})
        except Exception:
            _logger.warning('jewellery_actor re-stamp failed', exc_info=True)

    cr.precommit.add(run)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _jewellery_actor_targets(self):
        cr = self.env.cr
        ids = tuple(self.ids)
        cr.execute('SELECT id FROM product_product WHERE product_tmpl_id IN %s', (ids,))
        variant_ids = [r[0] for r in cr.fetchall()]
        cr.execute('SELECT id FROM jewellery_stone WHERE product_tmpl_id IN %s', (ids,))
        stone_ids = [r[0] for r in cr.fetchall()]
        return [
            ('product_template', 'product.template', self.ids, ()),
            ('product_product', 'product.product', variant_ids, ()),
            ('jewellery_stone', 'jewellery.stone', stone_ids, ()),
        ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        user = _actor_user(self.env)
        if user and records:
            self.env.flush_all()
            _restamp(self.env, user, records._jewellery_actor_targets())
        return records

    def write(self, vals):
        res = super().write(vals)
        user = _actor_user(self.env)
        if user and self:
            self.env.flush_all()
            _restamp(self.env, user, self._jewellery_actor_targets())
        return res

    def init_jewellery_from_customer(self, *args, **kwargs):
        res = super().init_jewellery_from_customer(*args, **kwargs)
        user = _actor_user(self.env)
        skus = [c for c in self.mapped('default_code') if c]
        if user and skus:
            self.env.flush_all()
            orders = self.env['purchase.order'].sudo().search([('origin', 'in', skus)])
            _restamp(self.env, user, [
                ('purchase_order', 'purchase.order', orders.ids, ('user_id',)),
            ])
        return res
