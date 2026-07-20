# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import hashlib
import json
import re
from decimal import ROUND_HALF_UP, Decimal

# Bar markup tiers: (weight_g, config_param_suffix). Weight 1000 means 1000g+.
BAR_TIER_WEIGHTS = [1, 2.5, 5, 10, 20, 31, 50, 100, 250, 500, 1000]
BAR_TIER_PARAM_SUFFIXES = [
    '1g', '2_5g', '5g', '10g', '20g', '31g', '50g', '100g', '250g', '500g', '1000g',
]
# Fallback EGP/gram when config param is missing or zero (same order as tiers above).
BAR_TIER_DEFAULT_MARKUP = [200.0, 200.0, 125.0,
                           120.0, 120.0, 115.0, 100.0, 100.0, 80.0, 80.0, 80.0]

# 1 (metric) carat = 0.2 grams.
CARAT_TO_GRAM = Decimal('0.2')


def _get_markup_bars_by_weight(env, weight_g: float) -> float:
    """
    Resolve bars markup per gram from weight using tier table (closest neighbor).
    Weights >= 1000 use the 1000g tier. Tie-break: use lower weight tier.
    Uses BAR_TIER_DEFAULT_MARKUP when the config param is missing or zero.
    """
    if weight_g <= 0:
        return 0.0
    ICP = env['ir.config_parameter'].sudo()
    if weight_g >= 1000:
        raw = ICP.get_param('jewellery_evaluator.markup_bars_1000g', '0.0')
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 0.0
        return val if val > 0 else BAR_TIER_DEFAULT_MARKUP[-1]
    # Closest tier by distance; tie -> lower weight
    best_weight = BAR_TIER_WEIGHTS[0]
    best_dist = abs(weight_g - best_weight)
    for w in BAR_TIER_WEIGHTS:
        if w >= 1000:
            continue
        d = abs(weight_g - w)
        if d < best_dist:
            best_dist = d
            best_weight = w
    idx = BAR_TIER_WEIGHTS.index(best_weight)
    param_key = f'jewellery_evaluator.markup_bars_{BAR_TIER_PARAM_SUFFIXES[idx]}'
    raw_value = ICP.get_param(param_key, '0.0')
    try:
        val = float(raw_value)
    except (TypeError, ValueError):
        val = 0.0
    return val if val > 0 else BAR_TIER_DEFAULT_MARKUP[idx]


def get_silver_markup_per_gram(env) -> float:
    """Read silver markup per gram from system parameters."""
    raw = env['ir.config_parameter'].sudo().get_param(
        'jewellery_evaluator.silver_markup_per_gram', '0.0'
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def get_silver_min_markup_per_gram(env) -> float:
    """Read the silver *minimum* making fee per gram (the price-floor fee).

    0 (the default) means 'auto' — the floor falls back to 70% of the making fee.
    """
    raw = env['ir.config_parameter'].sudo().get_param(
        'jewellery_evaluator.silver_markup_per_gram_min', '0.0'
    )
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def get_min_markup_per_gram(env, gold_type: str) -> float:
    """Read the *minimum* making fee per gram for a gold jewellery type — the
    fee used for the price floor (cost + min_fee × weight).

    Only local/foreign jewellery have their own minimum making fee; bars return
    0. 0 (the default) means 'auto' — the floor falls back to 70% of the making
    fee, so behaviour is unchanged until a minimum is configured.
    """
    if gold_type in ('jewellery_local', 'jewellery_foreign'):
        raw = env['ir.config_parameter'].sudo().get_param(
            f'jewellery_evaluator.markup_{gold_type}_min', '0.0'
        )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def get_markup_per_gram(env, gold_type: str, weight_g=None) -> float:
    """
    Read markup per gram from system parameters.

    For jewellery_local / jewellery_foreign, weight_g is ignored.
    For bars, weight_g is required; markup is resolved by weight tier (closest neighbor).

    Args:
        env: Odoo environment
        gold_type: Gold type key (jewellery_local, jewellery_foreign, bars)
        weight_g: Required when gold_type is 'bars'; used for tier lookup

    Returns:
        float: Markup per gram, 0.0 if not configured or invalid
    """
    if not gold_type:
        return 0.0

    if gold_type == 'bars':
        if weight_g is None or weight_g <= 0:
            return 0.0
        return _get_markup_bars_by_weight(env, weight_g)

    param_key = f'jewellery_evaluator.markup_{gold_type}'
    raw_value = env['ir.config_parameter'].sudo().get_param(param_key, '0.0')
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 0.0


def parse_gold_price_with_regex(text: str, pattern: str) -> float:
    """
    Extract 21K gold price from text using a configurable regex pattern.

    The pattern is applied to the text. If it has a capturing group, the first
    group is used as the price string; otherwise the full match is used. The
    result is parsed as a float (supports integers and decimals).

    Args:
        text: HTML or plain text response (e.g. from Gold API endpoint).
        pattern: Regular expression that matches the price. Prefer one capturing
            group containing the number (e.g. r'(\\d+(?:\\.\\d+)?)').

    Returns:
        float: Extracted 21K gold price per gram.

    Raises:
        ValueError: If pattern is invalid, no match, or parsed value is not a
            valid positive number.
    """
    if not pattern or not pattern.strip():
        raise ValueError('Gold 21K regex formula is empty.')

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f'Invalid Gold 21K regex formula: {e}') from e

    match = compiled.search(text)
    if not match:
        raise ValueError(
            'Price not found in API response (regex did not match).')

    if match.groups():
        extracted = match.group(1).strip()
    else:
        extracted = match.group(0).strip()

    if not extracted:
        raise ValueError('Price not found in API response (empty match).')

    # Allow digits and one decimal point; strip other characters for localization
    normalized = re.sub(r'[^\d.]', '', extracted)
    if not normalized:
        raise ValueError(
            f'Extracted value is not a valid number: {extracted!r}')

    try:
        price = float(normalized)
    except ValueError as e:
        raise ValueError(
            f'Extracted value is not a valid number: {extracted!r}') from e

    if price <= 0:
        raise ValueError(
            f'Invalid price extracted: {price} (must be greater than 0).')

    return price


def parse_silver_price_text(text: str) -> float:
    """
    Extract the first numeric value from the rendered text of a silver-price cell.

    Used after a headless browser has resolved the configured XPath selector for
    the silver 999 page; the cell typically contains text like '53.20 EGP'.

    Returns:
        float: Parsed price per gram.

    Raises:
        ValueError: When the text is empty or no positive number can be parsed.
    """
    if not text or not text.strip():
        raise ValueError('Silver price cell is empty.')
    cleaned = text.strip().replace(',', '')
    match = re.search(r'\d+(?:\.\d+)?', cleaned)
    if not match:
        raise ValueError(f'No numeric value found in silver price cell: {text!r}')
    try:
        price = float(match.group(0))
    except ValueError as e:
        raise ValueError(
            f'Silver price cell did not parse as a number: {text!r}') from e
    if price <= 0:
        raise ValueError(
            f'Invalid silver price: {price} (must be greater than 0).')
    return price


def compute_gold_product_price(
    base_gold_price_21k: float,
    purity: str,
    weight_g: float,
    markup_per_gram: float,
    min_markup_per_gram: float = 0.0,
) -> tuple[float, float, float]:
    """
    Compute gold product prices from base price, purity, weight, and markup.

    Args:
        base_gold_price_21k: Base 21K gold price per gram (from API)
        purity: Gold purity ('24K', '21K', '18K')
        weight_g: Weight of gold in grams
        markup_per_gram: Markup (making fee) per gram (from settings)
        min_markup_per_gram: Minimum making fee per gram for the price floor.
            When > 0 the floor is cost + (this × weight); when 0 (the default)
            it falls back to cost + 70% of the making fee.

    Returns:
        tuple: (cost_price, sale_price, min_sale_price)
            - cost_price: Cost price (base × purity_factor × weight)
            - sale_price: Sale price (cost + markup), rounded to nearest 50
            - min_sale_price: Minimum sale price (the floor), rounded to nearest 50
    """
    # Purity factors mapping (relative to 21K, which is what the API returns)
    # 24K = 8/7 of 21K; 18K = 7/8 of 21K
    purity_factors = {
        '24K': Decimal('8') / Decimal('7'),         # 8/7 of 21K
        '21K': Decimal('1.0'),                       # 1.0000
        '18K': Decimal('7') / Decimal('8'),          # 7/8 of 21K
    }

    purity_factor = purity_factors.get(purity, Decimal('0'))
    if purity_factor <= 0:
        raise ValueError(f'Invalid purity: {purity}')

    # Validate inputs
    if weight_g <= 0:
        raise ValueError(f'Weight must be greater than 0, got: {weight_g}')
    if base_gold_price_21k <= 0:
        raise ValueError(
            f'Base gold price must be greater than 0, got: {base_gold_price_21k}')
    if markup_per_gram < 0:
        raise ValueError(f'Markup cannot be negative, got: {markup_per_gram}')

    # Use Decimal for precise calculations
    weight = Decimal(str(weight_g))
    base_price = Decimal(str(base_gold_price_21k))
    markup = Decimal(str(markup_per_gram))

    # Calculate cost: (21K price from API) × purity_factor × weight
    adjusted_gold_price = base_price * purity_factor
    cost = (adjusted_gold_price * weight).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # Calculate markup total: markup × weight
    markup_total = (markup * weight).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # Calculate sale price: cost + markup_total
    sale_price = (cost + markup_total).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # Minimum sale price (the floor). If a minimum making fee per gram is
    # configured (> 0), the floor is cost + (min_making_fee × weight); otherwise
    # fall back to the legacy 70%-of-making-fee rule.
    if min_markup_per_gram and min_markup_per_gram > 0:
        min_markup_total = (Decimal(str(min_markup_per_gram)) * weight).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    else:
        min_markup_total = markup_total * Decimal('0.7')
    min_sale_price = (cost + min_markup_total).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # Round ONLY the sale price to the nearest 50. Cost and the minimum sale
    # price keep their exact (0.01) values — never rounded to 50.
    round_to_50 = Decimal('50')
    sale_price = (sale_price / round_to_50).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP
    ) * round_to_50

    return (float(cost), float(sale_price), float(min_sale_price))


def _get_diamond_config_float(env, param_suffix: str, default: float) -> float:
    """Read a single float config parameter for diamond jewellery, falling back to *default*."""
    raw = env['ir.config_parameter'].sudo().get_param(
        f'jewellery_evaluator.{param_suffix}', str(default)
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# Stone carat tiers: (min_carat_inclusive, max_carat_inclusive, config_param_suffix, hardcoded_default_usd_per_carat)
# All prices are per 1.00 carat; actual stone price = tier_price_per_carat × carat_weight
# Tier 5 applies to all stones >= 0.200 ct (unlimited)
_STONE_TIERS = [
    # Tier 1: 0.001–0.089 ct @ $800/ct
    (0.001, 0.089, 'diamond_stone_tier_1_usd', 800.0),
    # Tier 2: 0.090–0.109 ct @ $950/ct
    (0.090, 0.109, 'diamond_stone_tier_2_usd', 950.0),
    # Tier 3: 0.110–0.149 ct @ $1100/ct
    (0.110, 0.149, 'diamond_stone_tier_3_usd', 1100.0),
    # Tier 4: 0.150–0.199 ct @ $1250/ct
    (0.150, 0.199, 'diamond_stone_tier_4_usd', 1250.0),
    # Tier 5: 0.200 ct and above @ $1350/ct (unlimited)
    (0.200, 7.0, 'diamond_stone_tier_5_usd', 1350.0),
]


def get_stone_tier_price(env, carat: float) -> float:
    """
    Return the USD price for a stone of the given carat weight.

    Tiers 1–5 cover 0.001+ ct. Prices are stored per-carat (e.g., tier 1 = $800/ct),
    so actual stone price = tier_price_per_carat × carat_weight.
    Tier 5 ($1350/ct) applies to all stones >= 0.200 ct (unlimited).

    Example:
        For a 0.05 ct stone in Tier 1 (default $800/ct): price = $800 × 0.05 = $40.
        For a 5.0 ct stone in Tier 5 (default $1350/ct): price = $1350 × 5.0 = $6750.

    Args:
        env: Odoo environment.
        carat: Stone weight in carats.

    Returns:
        float: Calculated stone price in USD (tier_price_per_carat × carat_weight).
    """
    for lo, hi, param, default in _STONE_TIERS:
        if lo <= carat <= hi:
            price_per_carat = _get_diamond_config_float(env, param, default)
            # Multiply per-carat price by actual carat weight
            adjusted_price = (Decimal(str(price_per_carat)) * Decimal(str(carat))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            return float(adjusted_price)
    # Should never reach here with valid carat (constraints ensure 0.001–7.0)
    return 0.0


# ── Rapaport grid pricing (stones >= 0.25 ct) ────────────────────────────────
# The Rap price list is stored as two JSON grids (config params
# jewellery_evaluator.diamond_rap_round / _pear), each { bucket: { rowKey: {
# colKey: cell } } } where cell is the PDF number in *hundreds of USD per carat*
# (e.g. 54 -> $5,400/ct). Stones < 0.25 ct keep the 5-tier pricing above.
RAP_MIN_CARAT = 0.25

# (lo_inclusive, hi_inclusive, bucket_key, grouped_format)
_RAP_BUCKETS = [
    (0.230, 0.299, '0.23-0.29', True),
    (0.300, 0.399, '0.30-0.39', False),
    (0.400, 0.499, '0.40-0.49', False),
    (0.500, 0.699, '0.50-0.69', False),
    (0.700, 0.899, '0.70-0.89', False),
    (0.900, 0.999, '0.90-0.99', False),
    (1.000, 1.499, '1.00-1.49', False),
    (1.500, 1.999, '1.50-1.99', False),
    (2.000, 2.999, '2.00-2.99', False),
    (3.000, 3.999, '3.00-3.99', False),
    (4.000, 4.999, '4.00-4.99', False),
    (5.000, 9.999, '5.00-5.99', False),   # 6.00-9.99 ct fall into the 5-5.99 sheet
    (10.000, 99.0, '10.00-10.99', False),
]

# Stone clarity (LC/P1-P3) -> Rap column. Full (>= 0.30) vs grouped (0.23-0.29).
_RAP_CLARITY_FULL = {
    'LC': 'IF', 'VVS1': 'VVS1', 'VVS2': 'VVS2', 'VS1': 'VS1', 'VS2': 'VS2',
    'SI1': 'SI1', 'SI2': 'SI2', 'SI3': 'SI3',
    'P1': 'I1', 'P2': 'I2', 'P3': 'I3', 'I1': 'I1', 'I2': 'I2', 'I3': 'I3',
}
_RAP_CLARITY_GROUP = {
    'LC': 'IF-VVS', 'VVS1': 'IF-VVS', 'VVS2': 'IF-VVS', 'VS1': 'VS', 'VS2': 'VS',
    'SI1': 'SI1', 'SI2': 'SI2', 'SI3': 'SI3',
    'P1': 'I1', 'P2': 'I2', 'P3': 'I3', 'I1': 'I1', 'I2': 'I2', 'I3': 'I3',
}
# Stone colour -> grouped row (full uses the colour letter itself, N -> M).
_RAP_COLOUR_GROUP = {
    'D': 'DF', 'E': 'DF', 'F': 'DF', 'G': 'GH', 'H': 'GH',
    'I': 'IJ', 'J': 'IJ', 'K': 'KL', 'L': 'KL', 'M': 'MN', 'N': 'MN',
}
_RAP_FULL_COLOURS = 'DEFGHIJKLM'


def rap_bucket_for_carat(carat: float):
    """(bucket_key, grouped) for a carat, or (None, False) if below the grid."""
    for lo, hi, key, grouped in _RAP_BUCKETS:
        if lo <= carat <= hi:
            return key, grouped
    return None, False


def rap_keys(colour: str, clarity: str, grouped: bool):
    """Map a stone's colour + clarity to the (rowKey, colKey) for a bucket."""
    colour = (colour or '').upper()
    clarity = (clarity or '').upper()
    if grouped:
        return (
            _RAP_COLOUR_GROUP.get(colour, 'MN'),
            _RAP_CLARITY_GROUP.get(clarity, 'I3'),
        )
    row = colour if colour in _RAP_FULL_COLOURS else 'M'  # colour N -> M row
    return row, _RAP_CLARITY_FULL.get(clarity, 'I3')


def _rap_grid(env, sheet: str) -> dict:
    raw = env['ir.config_parameter'].sudo().get_param(
        f'jewellery_evaluator.diamond_rap_{sheet}'
    )
    try:
        grid = json.loads(raw or '{}')
        return grid if isinstance(grid, dict) else {}
    except (TypeError, ValueError):
        return {}


def rap_stone_price_usd(env, shape: str, carat: float, colour: str, clarity: str):
    """Per-stone (one unit) USD from the Rap grid, or None if no usable cell.

    price = cell(hundreds USD/ct) x 100 x carat x (1 - rap_discount_pct).
    Round shape -> round grid; Pear -> pear grid; all other shapes -> round grid.
    """
    sheet = 'pear' if shape == 'Pear' else 'round'
    bucket, grouped = rap_bucket_for_carat(carat)
    if not bucket:
        return None
    row, col = rap_keys(colour, clarity, grouped)
    cell = (_rap_grid(env, sheet).get(bucket) or {}).get(row, {}).get(col)
    try:
        cell = float(cell)
    except (TypeError, ValueError):
        return None
    if cell <= 0:
        return None
    disc = _get_diamond_config_float(env, 'diamond_rap_discount_pct', 0.0)
    price = (
        Decimal(str(cell)) * Decimal('100') * Decimal(str(carat))
        * (Decimal('1') - Decimal(str(disc)))
    )
    return float(price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def get_stone_price_usd(env, shape: str, carat: float, colour: str, clarity: str) -> float:
    """Per-stone (one unit) USD. Routes: < 0.25 ct -> 5 tiers; >= 0.25 ct -> Rap
    grid, falling back to the tier price when the grid has no cell (never zero)."""
    if carat < RAP_MIN_CARAT:
        return get_stone_tier_price(env, carat)
    rap = rap_stone_price_usd(env, shape, carat, colour, clarity)
    if rap is not None:
        return rap
    return get_stone_tier_price(env, carat)


def compute_diamond_jewellery_price(
    base_gold_price_21k_egp: float,
    gold_purity: str,
    weight_g: float,
    stone_prices_usd: list[float],
    exchange_rate_usd: float,
    fee_per_gram_usd: float,
    ticket_multiplier: float,
    ticket_discount: float,
    min_sale_pct: float = 0.0,
) -> dict:
    """
    Compute all pricing outputs for a diamond jewellery product.

    Formula
    -------
    Gold price per gram (USD) = (base_gold_price_21k_egp × purity_factor) / exchange_rate_usd
    Total gold cost (USD)     = (gold_price_per_gram + fee_per_gram_usd) × weight_g
    Total stones cost (USD)   = sum of all valid stone prices
    Ticket price (USD)        = (gold_cost + stones_cost) × ticket_multiplier
    Sale price (USD)          = ticket_price × (1 - ticket_discount)
    Sale price (EGP)          = sale_price_usd × exchange_rate_usd

    Args:
        base_gold_price_21k_egp: 21K gold price per gram in EGP (from gold.price.service).
        gold_purity:             '24K', '21K', or '18K'.
        weight_g:                Gold weight in grams.
        stone_prices_usd:        List of stone total prices (unit_price × quantity) in USD.
        exchange_rate_usd:       How many EGP = 1 USD.
        fee_per_gram_usd:        Fixed USD making fee per gram of gold.
        ticket_multiplier:       Multiply (gold + stones) to get ticket price.
        ticket_discount:         Fraction discounted off the ticket (e.g. 0.20 = 20% off).

    Returns:
        dict with keys: total_gold_cost_usd, total_stones_cost_usd,
        ticket_price_usd, sale_price_usd, sale_price_egp.
    """
    purity_factors = {
        '24K': Decimal('8') / Decimal('7'),
        '21K': Decimal('1'),
        '18K': Decimal('7') / Decimal('8'),
    }
    purity_factor = purity_factors.get(gold_purity, Decimal('0'))
    if purity_factor <= 0:
        raise ValueError(f'Unsupported gold purity: {gold_purity!r}')
    if exchange_rate_usd <= 0:
        raise ValueError('Exchange rate must be greater than 0.')

    base = Decimal(str(base_gold_price_21k_egp))
    rate = Decimal(str(exchange_rate_usd))
    fee = Decimal(str(fee_per_gram_usd))
    wt = Decimal(str(weight_g))

    gold_price_per_gram_usd = (base * purity_factor) / rate
    total_gold_cost_usd = (gold_price_per_gram_usd + fee) * wt

    total_stones_cost_usd = sum(
        (Decimal(str(p)) for p in stone_prices_usd), Decimal('0')
    )

    multiplier = Decimal(str(ticket_multiplier))
    discount = Decimal(str(ticket_discount))

    ticket_price_usd = (total_gold_cost_usd +
                        total_stones_cost_usd) * multiplier
    sale_price_usd = ticket_price_usd * (Decimal('1') - discount)
    sale_price_egp = sale_price_usd * rate

    two_dp = Decimal('0.01')
    round_to_50 = Decimal('50')
    sale_price_egp = (sale_price_egp / round_to_50).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP
    ) * round_to_50

    # Minimum sale price (the POS floor) = a configurable share of the sale
    # price. When pct is 0 this returns 0; the POS enforcement then applies its
    # own 80%-of-price fallback (like gold/silver), so 0 does NOT remove the
    # floor. Kept exact (0.01), not rounded to 50 — matching the gold/silver
    # min-sale-price convention.
    min_pct = Decimal(str(min_sale_pct))
    if min_pct > 0:
        min_sale_price_egp = (sale_price_egp * min_pct).quantize(
            two_dp, rounding=ROUND_HALF_UP
        )
    else:
        min_sale_price_egp = Decimal('0')

    return {
        'total_gold_cost_usd':   float(total_gold_cost_usd.quantize(two_dp, rounding=ROUND_HALF_UP)),
        'total_stones_cost_usd': float(total_stones_cost_usd.quantize(two_dp, rounding=ROUND_HALF_UP)),
        'ticket_price_usd':      float(ticket_price_usd.quantize(two_dp, rounding=ROUND_HALF_UP)),
        'sale_price_usd':        float(sale_price_usd.quantize(two_dp, rounding=ROUND_HALF_UP)),
        'sale_price_egp':        float(sale_price_egp),
        'min_sale_price_egp':    float(min_sale_price_egp),
    }


def compute_silver_product_price(
    base_silver_999_per_gram: float,
    weight_g: float,
    markup_per_gram: float,
    min_markup_per_gram: float = 0.0,
) -> tuple[float, float, float]:
    """
    Compute silver product prices from 999 price per gram, weight, and markup.

    Silver purity 999.0/999.9 are both treated as factor 1.0 (pure silver).

    Args:
        base_silver_999_per_gram: Silver 999 price per gram (EGP).
        weight_g: Weight in grams.
        markup_per_gram: Markup (making fee) per gram (from settings).
        min_markup_per_gram: Minimum making fee per gram for the price floor.
            When > 0 the floor is cost + (this × weight); when 0 (the default)
            it falls back to cost + 70% of the making fee.

    Returns:
        tuple: (cost_price, sale_price, min_sale_price)
            - cost_price: base_silver_999_per_gram * weight_g
            - sale_price: cost + markup_total, rounded to nearest 50
            - min_sale_price: the floor, rounded to nearest 50
    """
    if weight_g <= 0:
        raise ValueError(f'Weight must be greater than 0, got: {weight_g}')
    if base_silver_999_per_gram <= 0:
        raise ValueError(
            'Base silver 999 price per gram must be greater than 0, '
            f'got: {base_silver_999_per_gram}'
        )
    if markup_per_gram < 0:
        raise ValueError(f'Markup cannot be negative, got: {markup_per_gram}')

    weight = Decimal(str(weight_g))
    base_price = Decimal(str(base_silver_999_per_gram))
    markup = Decimal(str(markup_per_gram))

    cost = (base_price * weight).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    markup_total = (markup * weight).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    sale_price = (cost + markup_total).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    if min_markup_per_gram and min_markup_per_gram > 0:
        min_markup_total = (Decimal(str(min_markup_per_gram)) * weight).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    else:
        min_markup_total = markup_total * Decimal('0.7')
    min_sale_price = (cost + min_markup_total).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # Round ONLY the sale price to the nearest 50; cost and the minimum sale
    # price keep their exact (0.01) values.
    round_to_50 = Decimal('50')
    sale_price = (sale_price / round_to_50).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP
    ) * round_to_50

    return (float(cost), float(sale_price), float(min_sale_price))


def compute_diamond_weight_g(stone_carat_qty: list[tuple[float, int]]) -> float:
    """
    Total stone weight in grams for a piece.

    diamond_weight_g = sum over stones of (carat × quantity) × 0.2

    Every stone counts (there is no diamond-vs-gemstone discriminator). The
    carat→gram factor is the fixed metric carat (0.2 g).

    Args:
        stone_carat_qty: list of (carat, quantity) pairs, one per stone line.

    Returns:
        float: total stone weight in grams, rounded to 3 decimal places.
    """
    total_carats = sum(
        (Decimal(str(carat)) * Decimal(str(qty)) for carat, qty in stone_carat_qty),
        Decimal('0'),
    )
    grams = (total_carats * CARAT_TO_GRAM).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP
    )
    return float(grams)


def compute_weight_reading_g(gross_weight_g: float, ticket_weight_g: float) -> float:
    """
    Scale reading of the finished, labelled piece.

    weight_reading_g = gross_weight_g + ticket_weight_g

    Args:
        gross_weight_g: gold weight + diamond weight (grams).
        ticket_weight_g: fixed per-piece ticket/label weight (grams).

    Returns:
        float: weight reading in grams, rounded to 3 decimal places.
    """
    reading = (Decimal(str(gross_weight_g)) + Decimal(str(ticket_weight_g))).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP
    )
    return float(reading)


def compute_sku_prefix(default_code: str | None) -> str:
    """
    Extract the SKU prefix: the text before the first '-' in default_code.

    'RING-18K-001' → 'RING'; 'PLAIN' → 'PLAIN'; '' / None → ''; '-X' → ''.

    Args:
        default_code: the product's internal reference (may be empty/None).

    Returns:
        str: the prefix, or '' when default_code is empty.
    """
    if not default_code:
        return ''
    return default_code.split('-', 1)[0]


def get_ticket_weight_g(env) -> float:
    """Read the per-piece ticket weight (grams) from system parameters."""
    raw = env['ir.config_parameter'].sudo().get_param(
        'jewellery_evaluator.ticket_weight_g', '0.06'
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.06


def sha1_hex(text: str | None) -> str:
    """
    SHA-1 hex digest of a string — the same scheme Odoo POS uses (``Sha1.hash``).

    Used to hash the fallback master override PIN so only its digest, never the
    plaintext, is shipped to the register; the frontend reproduces it with the
    POS ``Sha1.hash()`` global. This matches how pos_hr hashes employee PIN/badge
    values, so the register can compare employee PIN, employee badge, and the
    master PIN with a single hash function.

    Args:
        text: the raw value (may be None/empty/whitespace).

    Returns:
        str: lowercase hex sha1 of the trimmed value, or '' when empty.
    """
    normalized = (text or "").strip()
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def format_weight_g(value: float) -> str:
    """Weight in grams — 2 decimals (like the invoice's gold column), trailing
    zeros trimmed: 2.70 -> '2.7', 0.200 -> '0.2', 0.076 -> '0.08', 3.0 -> '3'."""
    d = Decimal(str(value or 0)).quantize(Decimal("0.01")).normalize()
    if d == 0:
        return "0"
    return f"{d:f}"


def format_carat(value: float) -> str:
    """Carat — 3 decimals, trailing zeros trimmed: 1.010 -> '1.01', 0.362 ->
    '0.362', 0.024 -> '0.024'."""
    d = Decimal(str(value or 0)).quantize(Decimal("0.001")).normalize()
    if d == 0:
        return "0"
    return f"{d:f}"


def format_diamond_note(stones: list[dict]) -> str:
    """Auto invoice note for a diamond piece, from its stone rows.

    Each row is a dict with ``carat`` and ``quantity``. A single stone renders
    ``'<carat> CR'``; a group of N identical stones renders ``'N DR. <carat>'``;
    multiple groups are joined with ' + '. Returns e.g. ``'Diamond 1.01 CR'`` or
    ``'Diamond 15 DR. 0.362'``; empty string when there are no stones.
    """
    parts: list[str] = []
    for stone in stones:
        carat = format_carat(stone.get("carat", 0))
        qty = int(stone.get("quantity") or 1)
        parts.append(f"{qty} DR. {carat}" if qty > 1 else f"{carat} CR")
    return ("Diamond " + " + ".join(parts)) if parts else ""
