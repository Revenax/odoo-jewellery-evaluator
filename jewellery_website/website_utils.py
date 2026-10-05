# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Pure rules for the online catalogue: no Odoo imports, unit-tested in tests/.

Products are named by SKU (the ops app sets name = SKU), which is right for the
till and wrong for a shop window. These functions turn the jewellery fields into
a customer-facing title, decide which eCommerce categories a piece belongs in,
and decide whether it should be on sale online at all.
"""

NEW_ARRIVAL_DAYS = 30

# The eCommerce category tree, mirroring the Shopify store's collections
# (marjaanjewellery.com): (key, name, parent_key, sequence).
PUBLIC_TREE = (
    ('new_arrivals', 'New Arrivals', None, 1),
    ('rings', 'Rings', None, 10),
    ('gold_rings', 'Gold Rings', 'rings', 1),
    ('diamond_rings', 'Diamond Rings', 'rings', 2),
    ('twin_rings', 'Diamond Twins', 'rings', 3),
    ('bands', 'Wedding Bands', 'rings', 4),
    ('necklaces', 'Necklaces', None, 20),
    ('gold_necklaces', 'Gold Necklaces', 'necklaces', 1),
    ('diamond_necklaces', 'Diamond Necklaces', 'necklaces', 2),
    ('chains', 'Chains', 'necklaces', 3),
    ('pendants', 'Pendants', 'necklaces', 4),
    ('earrings', 'Earrings', None, 30),
    ('gold_earrings', 'Gold Earrings', 'earrings', 1),
    ('diamond_earrings', 'Diamond Earrings', 'earrings', 2),
    ('piercings', 'Piercings', 'earrings', 3),
    ('bracelets', 'Bracelets', None, 40),
    ('gold_bracelets', 'Gold Bracelets', 'bracelets', 1),
    ('diamond_bracelets', 'Diamond Bracelets', 'bracelets', 2),
    ('bars_coins', 'Gold Bars & Coins', None, 50),
    ('gold_bars', 'Gold Bars', 'bars_coins', 1),
    ('gold_coins', 'Gold Coins', 'bars_coins', 2),
    ('loose_diamonds', 'Loose Diamonds', None, 60),
    ('collections', 'Collections', None, 70),
    ('gold_collection', 'Gold Collection', 'collections', 1),
    ('diamond_collection', 'Diamond Collection', 'collections', 2),
)

# Internal product category, by complete_name ("Gold / Ring": a Ring under Gold;
# match on complete_name, never name, which is just "Ring") -> eCommerce leaf.
CATEGORY_LEAF = {
    'Gold / Ring': 'gold_rings',
    'Gold / Bands': 'bands',
    'Diamond / Ring': 'diamond_rings',
    'Diamond / Twin Ring': 'twin_rings',
    'Diamond / Bands': 'bands',
    'Gold / Necklace': 'gold_necklaces',
    'Diamond / Necklace': 'diamond_necklaces',
    'Gold / Chain': 'chains',
    'Gold / Pendant': 'pendants',
    'Diamond / Pendant': 'pendants',
    'Gold / Earrings': 'gold_earrings',
    'Diamond / Earrings': 'diamond_earrings',
    'Gold / Piercing': 'piercings',
    'Gold / Bracelet': 'gold_bracelets',
    'Diamond / Bracelet': 'diamond_bracelets',
    'Gold / Bar': 'gold_bars',
    'Gold / Ingot': 'gold_bars',
    'Gold / Coin': 'gold_coins',
    'Diamond / Center Stone': 'loose_diamonds',
}

# Investment gold and loose stones are not "jewellery collections".
_NOT_IN_COLLECTIONS = {'gold_bars', 'gold_coins', 'loose_diamonds'}


def _split_category(category_name):
    """'Gold / Twin Ring' -> ('Gold', 'Twin Ring'); anything else -> (None, None)."""
    if not category_name or '/' not in category_name:
        return None, None
    parts = [p.strip() for p in category_name.split('/')]
    if len(parts) < 2 or not parts[0] or not parts[-1]:
        return None, None
    return parts[0], parts[-1]


def _fmt_weight(grams):
    """10.0 -> '10', 4.45 -> '4.45', 31.1 -> '31.10' (jewellers quote two places)."""
    g = round(float(grams), 2)
    return str(int(g)) if g == int(g) else f'{g:.2f}'


def _fmt_carat(carat):
    """0.52 -> '0.52', 1.25 -> '1.25', 0.045 -> '0.045', 2.0 -> '2.00'."""
    s = f'{round(float(carat), 3):.3f}'.rstrip('0')
    whole, _, frac = s.partition('.')
    return f'{whole}.{frac.ljust(2, "0")}'


def website_title(category_name, jewellery_type, purity, weight_g, total_carat, sku=None):
    """Customer-facing title, or None when the piece is not jewellery we can describe.

    18K Gold Ring · 4.45 g        Diamond Ring · 18K Gold · 0.52 ct
    24K Gold Bar · 10 g           Loose Diamond · 0.75 ct
    Diamond Twin Ring · 18K Gold · 0.31 ct · Ring A
    """
    material, kind = _split_category(category_name)
    if not kind:
        return None
    weight = float(weight_g or 0)
    carat = float(total_carat or 0)
    if jewellery_type == 'center_stone' or kind == 'Center Stone':
        parts = ['Loose Diamond']
        if carat > 0:
            parts.append(f'{_fmt_carat(carat)} ct')
    elif jewellery_type == 'diamond_jewellery' or material == 'Diamond':
        parts = [f'Diamond {kind}']
        if purity:
            parts.append(f'{purity} Gold')
        if carat > 0:
            parts.append(f'{_fmt_carat(carat)} ct')
    elif jewellery_type == 'silver' or material == 'Silver':
        parts = [f'Silver {kind}']
        if weight > 0:
            parts.append(f'{_fmt_weight(weight)} g')
    else:
        parts = [f'{purity} Gold {kind}' if purity else f'Gold {kind}']
        if weight > 0:
            parts.append(f'{_fmt_weight(weight)} g')
    if kind == 'Twin Ring' and sku and sku[-1:] in ('A', 'B'):
        parts.append(f'Ring {sku[-1]}')
    return ' · '.join(parts)


def public_category_keys(category_name, is_new=False):
    """eCommerce category keys for a product, from its internal category.

    The leaf (e.g. gold_rings, whose parent Rings then lists it too), its
    material collection, and New Arrivals when recent. [] = not sold online.
    """
    leaf = CATEGORY_LEAF.get((category_name or '').strip())
    if not leaf:
        return []
    keys = [leaf]
    material, _ = _split_category(category_name)
    if leaf not in _NOT_IN_COLLECTIONS:
        if material == 'Gold':
            keys.append('gold_collection')
        elif material == 'Diamond':
            keys.append('diamond_collection')
    if is_new:
        keys.append('new_arrivals')
    return keys


def should_publish(active, sale_ok, has_image, price, free_qty, sellable_category):
    """A piece is on the website exactly when a customer could actually buy it:
    a sellable category, a photo, a real price, and at least one free in stock.
    Sold or reserved one-of-a-kind pieces (free 0) come off; nothing is shown
    without a photo or at 0 EGP."""
    return bool(
        active and sale_ok and sellable_category and has_image
        and (price or 0) > 0 and (free_qty or 0) >= 1
    )


def web_order_summary(reference, total, currency, delivery, store, payment, skus, customer):
    """One line telling the boutique a web order needs action, e.g.
    "S00012 — 514,400 EGP · Pick up in store: Sway Mall · Pay on Site · DRL8-0149 · Sara".
    Lists at most five pieces; empty parts are left out."""
    pieces = ', '.join(skus[:5]) + (f' +{len(skus) - 5} more' if len(skus) > 5 else '')
    where = f'{delivery}: {store}' if delivery and store else (delivery or store)
    parts = [f'{reference} — {total:,.0f} {currency}', where, payment, pieces, customer]
    return ' · '.join(part for part in parts if part)
