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
from markupsafe import Markup

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

# ── public URLs: https, the real host ───────────────────────────────────
# nginx now sends X-Forwarded-Host, so Odoo sees https; fix the stored base URL
# (canonical links, sitemap, emails, payment return URLs) and pin the domain.
ICP = env['ir.config_parameter'].sudo()
base = ICP.get_param('web.base.url') or ''
if base.startswith('http://odoo.marjaanjewellery.com'):
    ICP.set_param('web.base.url', base.replace('http://', 'https://', 1))
    log(f'web.base.url: {base} -> https')
if not W.domain:
    W.domain = 'https://odoo.marjaanjewellery.com'
    log(f'website domain set: {W.domain} (change at the domain cutover from Shopify)')

# ── analytics: the same accounts the Shopify store reports to ───────────
# Read off marjaanjewellery.com (2026-10-06). Both load only after the visitor
# accepts optional cookies; filter reports by hostname to split Odoo/Shopify.
GA4, META_PIXEL = 'G-1GP4YDWNEM', '3903840599865457'
GSC_TOKEN = 'VvJlqkdrmwEuARJfeCuK4Pjlw0RK3lEoc1pQ2HYPAow'
if not W.google_analytics_key:
    W.google_analytics_key = GA4
    log(f'Google Analytics: {GA4} (with ecommerce events)')
if not W.meta_pixel_id:
    W.meta_pixel_id = META_PIXEL
    log(f'Meta pixel: {META_PIXEL} (page view, view content, add to cart, purchase)')
# custom_code_head is an Html field: its value is Markup, and str + Markup
# HTML-escapes the str half. The first run of this block did exactly that and
# printed the tag as text at the top of every page; repair it, then write Markup.
GSC_TAG = Markup(f'<meta name="google-site-verification" content="{GSC_TOKEN}"/>')
head = W.custom_code_head or Markup('')
escaped = Markup.escape(str(GSC_TAG))
if escaped in head:
    head = Markup(str(head).replace(str(escaped) + '\n', '').replace(str(escaped), ''))
    W.custom_code_head = head
    log('Search Console tag un-escaped (it was showing as text on every page)')
if str(GSC_TAG) not in str(head):
    W.custom_code_head = GSC_TAG + Markup('\n') + head
    log('Search Console verification meta tag added (keeps the property verified after cutover)')

# ── internal provenance tags are not shop filters ───────────────────────
# "Lented" (consignment) and "Bought from Customer" (buy-backs) are how the
# boutique tracks where a piece came from; customers saw them as filters.
for tag in env['product.tag'].search([('name', 'in', ['Lented', 'Bought from Customer'])]):
    if tag.visible_to_customers:
        tag.visible_to_customers = False
        log(f'product tag "{tag.name}" hidden from the shop (internal provenance)')

# ── no "Sign in" button in the header (owner, 2026-10-06) ───────────────
# Same as the editor's Header > "Show Sign In" toggle: deactivating the view
# in website context makes a website-specific copy (survives module updates).
# Customers can still sign in at checkout or via /web/login.
signin = env['ir.ui.view'].with_context(website_id=W.id, active_test=False).search(
    [('key', '=', 'portal.user_sign_in')]).filter_duplicate()
if signin.active:
    signin.write({'active': False})
    log('header "Sign in" button removed')

# ── bullion is banned online (owner, legal, 2026-10-06) ─────────────────
for key in ('gold_bars', 'gold_coins', 'bars_coins'):
    cat = env.ref(f'jewellery_website.public_categ_{key}', raise_if_not_found=False)
    if cat:
        cat.product_tmpl_ids.write({'is_published': False})
        log(f'eCommerce category "{cat.name}" deleted (bullion may not be sold online)')
        cat.unlink()
for m in env['website.menu'].search([('website_id', '=', W.id), '|', ('name', 'ilike', 'bar'), ('name', 'ilike', 'coin')]):
    log(f'menu "{m.name}" removed (bullion)')
    m.unlink()

# ── pickup: Sway Mall only (owner, 2026-10-06) ──────────────────────────
sm = env['stock.warehouse'].search([('code', '=', 'SM')], limit=1)
company_partner = W.company_id.partner_id
for carrier in env['delivery.carrier'].search([('delivery_type', '=', 'in_store')]):
    if carrier.warehouse_ids != sm:
        log(f'pickup stores: {carrier.warehouse_ids.mapped("code")} -> [SM]')
        carrier.warehouse_ids = [(6, 0, sm.ids)]
sm_addr = {'street': 'Sway Mall, Mohamed Naguib St.', 'city': 'New Cairo', 'country_id': egypt.id}
if sm.partner_id != company_partner and sm.partner_id.street != sm_addr['street']:
    # 0/0 makes Click & Collect geolocate the address on first use.
    sm.partner_id.write({**sm_addr, 'partner_latitude': 0, 'partner_longitude': 0})
    log('Sway Mall pickup address set')

# ── keep search engines out until the domain moves from Shopify ─────────
ROBOTS = Markup('User-agent: *\nDisallow: /')
if str(W.robots_txt or '').strip() != str(ROBOTS):
    W.robots_txt = ROBOTS
    log('robots.txt: Disallow all (pre-launch; remove at the cutover)')

# ── /privacy and /about-us: real text instead of an empty heading ───────
PAGE_TEXT = {
    '/privacy': ('Privacy Policy', """
<p>This policy explains what personal information Marjaan Jewellery collects through this website, why, and what we do with it. It is written to comply with Egypt's Personal Data Protection Law (Law No. 151 of 2020).</p>
<h2 class="h4 mt-4">What we collect</h2>
<ul>
<li><b>Orders and accounts:</b> your name, email address, phone number and, for delivery, your address. We need these to process, deliver and support your order.</li>
<li><b>Payments:</b> card payments are handled by our payment provider, Kashier. Your card details go directly to them; we never see or store your full card number.</li>
<li><b>Messages:</b> what you send us through the contact form or by email.</li>
<li><b>Browsing:</b> essential cookies keep your session and cart working. Only if you accept optional cookies do we use Google Analytics and the Meta (Facebook/Instagram) pixel, to understand how the site is used and to measure our advertising.</li>
</ul>
<h2 class="h4 mt-4">How we use it</h2>
<p>To fulfil and support your orders, issue invoices, answer your questions, keep the site secure, and improve the shop. We send marketing messages only if you have agreed to receive them, and you can unsubscribe at any time.</p>
<h2 class="h4 mt-4">Who we share it with</h2>
<p>Only the service providers needed to run the shop: our payment provider, our email provider, delivery partners for delivered orders, and the analytics services above when you have consented. We do not sell your personal information.</p>
<h2 class="h4 mt-4">How long we keep it</h2>
<p>Order and invoice records are kept as long as the law requires. Other information is kept only as long as needed for the purposes above.</p>
<h2 class="h4 mt-4">Your rights</h2>
<p>You may ask to see, correct or delete your personal information, or withdraw your consent, at any time. You can change your cookie choice from the cookie banner.</p>
<h2 class="h4 mt-4">Contact</h2>
<p>Marjaan Jewellery, Sway Mall, Mohamed Naguib St., New Cairo, Egypt. Email <a href="mailto:info@marjaanjewellery.com">info@marjaanjewellery.com</a>.</p>
"""),
    '/about-us': ('About Marjaan', """
<p class="lead">Marjaan is an Egyptian jewellery house creating fine gold and diamond jewellery.</p>
<p>Each piece is designed as a modern heirloom: refined, wearable, and made to last. Our collections span 18K and 21K gold and diamond jewellery, from everyday rings, bracelets and necklaces to statement pieces and loose diamonds.</p>
<p>Every piece in our shop is one of a kind and listed with its exact weight, karat and stones, so you know precisely what you are buying.</p>
<h2 class="h4 mt-4">Visit us</h2>
<p>Sway Mall, Mohamed Naguib St., New Cairo. Orders placed online can be collected and paid for in store.</p>
<p>Questions? Write to <a href="mailto:info@marjaanjewellery.com">info@marjaanjewellery.com</a>.</p>
"""),
}
for url, (title, body) in PAGE_TEXT.items():
    pages = env['website.page'].search([('url', '=', url), ('website_id', 'in', [W.id, False])], order='id')
    if not pages:
        continue
    served, demo = pages[0], pages[1:]
    if demo:
        log(f'{url}: {len(demo)} hidden theme-demo copies deleted')
        demo.unlink()
    marker = 'o_jewellery_page_text'
    if marker not in (served.arch or ''):
        served.arch = f"""<t name="{title}" t-name="{served.key}">
    <t t-call="website.layout">
        <div id="wrap" class="oe_structure">
            <section class="pt8 pb48 {marker}">
                <div class="container">
                    <h1 class="pt16 h2-fs">{title}</h1>
{body}
                </div>
            </section>
        </div>
    </t>
</t>"""
        log(f'{url}: content written ("{title}")')

# ── brand colours instead of the theme's lilac preset ───────────────────
# The theme palette (preset "default-light-4": #CDB4DB / #FFDAE8 / #765378)
# drives buttons, links, the cookie bar and the footer, so they came out
# purple next to the designer's ink/rose/cream page. Same mechanism as the
# editor's colour picker: Theme > Colors writes these keys.
BRAND = {
    'o-color-1': '#1A1A24',  # primary: buttons, links (designer's ink)
    'o-color-2': '#E99894',  # secondary: the designer's rose accent
    'o-color-3': '#FAF5F0',  # light sections and footer = page cream
    'o-color-4': '#FFFFFF',  # card / body white
    'o-color-5': '#1A1A24',  # dark sections and text
}
palette_url = '/website/static/src/scss/options/colors/user_color_palette.scss'
assets = env['website.assets'].with_context(website_id=W.id)


def custom_palette():
    att = assets._get_custom_attachment(assets._make_custom_asset_url(palette_url, 'web.assets_frontend'))
    return (att[:1].raw or b'').decode()


if any(f"'{k}': {v}" not in custom_palette() for k, v in BRAND.items()):
    assets.make_scss_customization(palette_url, BRAND)
    log(f'theme colours: lilac preset -> brand {BRAND}')

# ── /refund-policy: the homepage links it; it 404'd ─────────────────────
# Text = the owner's live Shopify policy (marjaanjewellery.com/policies/
# refund-policy, 2026-10-06), unchanged. Platform-neutral, unlike Shopify's
# generated privacy policy, which describes Shopify and needs the owner.
REFUND_ARCH = '''<t name="Returns and Refunds Policy" t-name="website.refund_policy">
    <t t-call="website.layout">
        <div id="wrap" class="oe_structure">
            <section class="pt8 pb48">
                <div class="container">
                    <h1 class="pt16 h2-fs">Returns and Refunds Policy</h1>
                    <p>We want you to be completely satisfied with your purchase. If you need to return or exchange an item, please review our policy below:</p>
                    <h2 class="h4 mt-4">Eligibility for Returns</h2>
                    <p>To be eligible for a return or refund, products must be returned in their original condition, with the attached label and packaging. An order receipt (either soft or hard copy) must also be included.</p>
                    <h2 class="h4 mt-4">Full Refund</h2>
                    <p>A full refund is available if the return is initiated within 24 hours of receiving your order.</p>
                    <h2 class="h4 mt-4">Refund Within 14 Days</h2>
                    <p>If you wish to return the product within 14 days but after the initial 24 hours, a refund will be processed with a deduction of 10% of the product price.</p>
                    <h2 class="h4 mt-4">Exchanges</h2>
                    <p>Exchanges are available within 14 days from the date of purchase and do not incur any deductions from the product price.</p>
                    <h2 class="h4 mt-4">How to Initiate a Return or Exchange</h2>
                    <p>To initiate a return or exchange, please contact our customer service at <a href="mailto:info@marjaanjewellery.com">info@marjaanjewellery.com</a> with your order number and details regarding the product you wish to return or exchange.</p>
                    <p>We appreciate your understanding and are here to help ensure your shopping experience is enjoyable!</p>
                </div>
            </section>
        </div>
    </t>
</t>'''
if not env['website.page'].search([('url', '=', '/refund-policy'), ('website_id', 'in', [W.id, False])]):
    env['website.page'].create({
        'name': 'Returns and Refunds Policy', 'url': '/refund-policy', 'website_id': W.id,
        'type': 'qweb', 'key': 'website.refund_policy', 'arch': REFUND_ARCH,
        'is_published': True, 'website_indexed': True,
    })
    log('page /refund-policy created from the live Shopify policy text')

# ── pickup stores: one contact per branch ───────────────────────────────
# Click & Collect lists each store by its warehouse's contact. All branches
# shared the company contact, so customers saw "Marjaan Jewellery" four times
# with no address. Give each pickup branch its own contact, named after it.
# Street/city/opening hours are the owner's to fill in (Inventory > Warehouses);
# coordinates are parked at 1000 so Odoo doesn't geolocate a country-only
# address and pin every store at the centre of Egypt. Reset them to 0 (or use
# the contact's "Compute based on address") once the real address is in.
company_partner = W.company_id.partner_id
for carrier in env['delivery.carrier'].search([('delivery_type', '=', 'in_store')]):
    for wh in carrier.warehouse_ids.filtered(lambda w: w.partner_id == company_partner):
        contact = env['res.partner'].create({
            'name': wh.name, 'parent_id': company_partner.id, 'type': 'other',
            'country_id': egypt.id, 'phone': company_partner.phone, 'email': company_partner.email,
            'partner_latitude': 1000, 'partner_longitude': 1000,
        })
        wh.partner_id = contact
        log(f'pickup store "{wh.name}": own contact #{contact.id} (address to fill in)')

env.cr.commit()
# A shell run does not tell the running workers their caches are stale (an
# HTTP request does, at its end): without this they keep serving the old
# compiled CSS/JS bundle and cached views.
env.registry.clear_cache('assets')
env.registry.clear_cache('templates')
env.registry.signal_changes()
print('CFG done,', len(LOG), 'changes')
