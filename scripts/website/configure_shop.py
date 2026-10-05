# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""One-time shop configuration for the Marjaan website (idempotent; safe to re-run).

Run through the Odoo shell AFTER jewellery_website is installed:
  sudo -u odoo bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < configure_shop.py'

Owner decisions baked in (2026-10-06): no cash on delivery; free standard shipping
is fine (limited to Egypt); in-store pickup + pay in store is the safe default
until a payment gateway exists.
"""
LOG = []


def log(msg):
    LOG.append(msg)
    print('CFG', msg)


W = env['website'].browse(1)
Cat = lambda key: env.ref(f'jewellery_website.public_categ_{key}')  # noqa: E731


def cat_url(key):
    return '/shop/category/' + env['ir.http']._slug(Cat(key))


# ── accounts & checkout ──────────────────────────────────────────────────
if W.auth_signup_uninvited != 'b2c':
    log(f'customer signup: {W.auth_signup_uninvited} -> b2c (shoppers can create accounts)')
    W.auth_signup_uninvited = 'b2c'
if W.account_on_checkout != 'optional':
    log(f'account on checkout: {W.account_on_checkout} -> optional (guest checkout allowed)')
    W.account_on_checkout = 'optional'

# ── catalogue order: newest pieces first ────────────────────────────────
sorts = dict(W._get_product_sort_mapping())
if 'publish_date desc' in sorts and W.shop_default_sort != 'publish_date desc':
    log(f'shop default sort: {W.shop_default_sort} -> publish_date desc ({sorts["publish_date desc"]})')
    W.shop_default_sort = 'publish_date desc'

# ── payments: no cash on delivery (owner decision) ──────────────────────
for p in env['payment.provider'].search([('name', 'ilike', 'cash on delivery')]):
    if p.state != 'disabled' or p.is_published:
        log(f'payment "{p.name}": {p.state}/published={p.is_published} -> disabled')
        p.write({'state': 'disabled', 'is_published': False})

# ── delivery: free standard shipping stays, Egypt only ──────────────────
egypt = env.ref('base.eg')
std = env['delivery.carrier'].search([('delivery_type', '=', 'fixed'), ('name', 'ilike', 'standard')], limit=1)
if std and set(std.country_ids.ids) != {egypt.id}:
    log(f'"{std.name}" (free) limited to Egypt (was {std.country_ids.mapped("code") or "all countries"})')
    std.country_ids = [(6, 0, [egypt.id])]

# ── menus: real category pages instead of the static mock-ups ───────────
MENU_TO_CATEGORY = {
    'New Arrivals': 'new_arrivals', 'Collections': 'collections', 'Rings': 'rings',
    'Necklaces': 'necklaces', 'Earrings': 'earrings', 'Bracelets': 'bracelets',
}
for m in env['website.menu'].search([('website_id', '=', W.id)]):
    key = MENU_TO_CATEGORY.get(m.name)
    if key and m.url != cat_url(key):
        log(f'menu "{m.name}": {m.url} -> {cat_url(key)}')
        m.url = cat_url(key)
    if m.name == 'Offers' and m.url == '/offers' and not env['website.page'].search([('url', '=', '/offers')]):
        log('menu "Offers" removed: /offers has no page and there is no offers programme yet')
        m.unlink()

# ── redirects: the homepage still links the old static URLs ─────────────
REDIRECTS = {
    '/rings': 'rings', '/necklaces': 'necklaces', '/earrings': 'earrings',
    '/bracelets': 'bracelets', '/new-arrival': 'new_arrivals', '/collections': 'collections',
}
Rewrite = env['website.rewrite']
for url_from, key in REDIRECTS.items():
    target = cat_url(key)
    r = Rewrite.search([('url_from', '=', url_from), ('website_id', '=', W.id)], limit=1)
    if not r:
        Rewrite.create({'name': f'{url_from} -> shop category', 'url_from': url_from, 'url_to': target,
                        'redirect_type': '301', 'website_id': W.id})
        log(f'redirect 301 {url_from} -> {target}')
    elif r.url_to != target:
        r.url_to = target
        log(f'redirect updated {url_from} -> {target}')

# ── theme demo categories nobody sells (0 products each) ────────────────
for name in ('Watches', 'Brooches', 'Anklets', 'Sets'):
    c = env['product.public.category'].search([('name', '=', name), ('parent_id', '=', False)])
    if c and not c.product_tmpl_ids and not c.child_id:
        log(f'removed empty theme demo category "{name}"')
        c.unlink()

env.cr.commit()
print('CFG done,', len(LOG), 'changes')
