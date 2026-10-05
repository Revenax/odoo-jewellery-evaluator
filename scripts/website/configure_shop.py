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

# ── homepage: featured grid from live pieces, not 8 hand-typed mock cards ─
# The homepage is a website-specific page view (the design's static grid had
# fake names, fake prices and blank images). Swap only the grid for a dynamic
# snippet; the section, its header and the design CSS stay as designed.
FEATURED = (
    '<div class="s_dynamic_snippet s_dynamic o_dynamic_snippet_empty o_jewellery_featured"'
    ' data-snippet="s_dynamic_snippet" data-name="Featured products"'
    ' data-filter-id="{filter_id}"'
    ' data-template-key="jewellery_website.dynamic_filter_template_product_product_featured_card"'
    ' data-number-of-records="8" data-number-of-elements="4" data-number-of-elements-small-devices="2"'
    ' data-extra-classes="featured-grid" data-column-classes="d-flex flex-column px-0">'
    '<div class="dynamic_snippet_template"/></div>'
)
home = env['ir.ui.view'].search([('key', '=', 'website.homepage'), ('website_id', '=', W.id)], limit=1)
if home:
    from lxml import etree
    arch = etree.fromstring(home.arch_db)
    static_grids = arch.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' featured-grid ')]"
        "[not(ancestor::*[contains(@class, 'o_jewellery_featured')])]")
    newest = env.ref('website_sale.dynamic_filter_newest_products')
    for grid in static_grids:
        new = etree.fromstring(FEATURED.format(filter_id=newest.id))
        new.tail = grid.tail
        grid.getparent().replace(grid, new)
    if static_grids:
        home.arch_db = etree.tostring(arch, encoding='unicode')
        log(f'homepage featured grid: {len(static_grids)} static mock grid(s) -> live "{newest.name}" (8 pieces)')

env.cr.commit()
print('CFG done,', len(LOG), 'changes')
