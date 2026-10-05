# Website launch checklist

State of the Odoo shop at https://odoo.marjaanjewellery.com as of 2026-10-06.
Shopify (marjaanjewellery.com) is still the live store.

## Wired and live

| Area | What it does |
|---|---|
| Catalogue | 855 pieces published by `jewellery_website` (every 15 min): a piece is live while it has free stock, a photo and a price, and comes off when it sells or is reserved. Titles like "Diamond Ring · 18K Gold · 0.52 ct" replace the till's SKU names everywhere a customer looks. |
| Categories | Shopify collections mirrored (Rings, Necklaces, Earrings, Bracelets, Gold Bars & Coins, Loose Diamonds, Collections, New Arrivals) and assigned from each piece's internal category. |
| Navigation | Menus point at the real category pages; the design's static URLs (`/rings`, `/new-arrival`, …) 301 to them. |
| Homepage | "Featured products" shows the 8 newest live pieces in the designer's card style (it was 8 hand-typed mock cards). |
| Product page | Reference, karat, weight and every stone (count, shape, carat, colour, clarity). Stone cost prices are never exposed. |
| Checkout | Guest checkout, sign-up open. Pick up in store + Pay on Site configured (not yet tried with a real order). Free standard delivery (Egypt only). No cash on delivery (owner decision). |
| Pickup stores | Sway Mall, Ismail Ramzy, Black Closet, Abbassi Sagha, each with its own contact (addresses still blank — see below). |
| Analytics | GA4 `G-1GP4YDWNEM` and Meta pixel `3903840599865457` (the Shopify store's own IDs), both only after cookie consent. Ecommerce events (view, add to cart, checkout, purchase) carry title, SKU and category. Odoo's own visitor tracking is on. Filter GA/Meta reports by hostname to separate Odoo from Shopify. |
| SEO | https canonical URLs and sitemap; Search Console verification tag carried over. |
| Policies | `/refund-policy` (copied unchanged from the live Shopify policy), `/cookie-policy`. |
| Order alerts | A confirmed web order sends a Pulse `web-order-placed` notification (reference, total, store, payment, SKUs). Subscribe to the topic in Pulse to receive it. |

Re-apply or audit the configuration at any time (idempotent):

```
sudo -u odoo bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < scripts/website/configure_shop.py'
```

## Blockers (need the owner or an outside account)

1. **Payment gateway.** Only Pay on Site exists, and Odoo allows it only with in-store pickup. A customer who picks delivery reaches payment with no method and cannot finish. Needs a merchant account (Paymob, Fawry, Kashier, Stripe…) and its API keys.
2. **Outgoing email (SMTP).** No mail server is configured: customers get no order confirmation, sign-up or password-reset email, and abandoned-cart emails are off. Needs SMTP credentials for a sending domain (e.g. Google Workspace or Amazon SES for marjaanjewellery.com, with SPF/DKIM).
3. **Store addresses and opening hours.** The four pickup contacts have no street, city or hours (Inventory › Configuration › Warehouses › contact; hours via Opening Hours). After entering an address, reset the contact's latitude/longitude to 0 (or press "Compute based on address") so the map shows the right pin. Also: should Black Closet and Abbassi Sagha be pickup points at all?
4. **Company address and tax ID** are empty (Settings › Companies). They print on order confirmations and invoices.
5. **Photos.** 153 in-stock pieces stay hidden only because they have no photo: 57 Diamond Twin Rings, 51 Center Stones, 17 Diamond Bracelets, 9 Diamond Necklaces, 9 Diamond Rings, 7 Diamond Bands, 2 Gold Earrings, 1 Diamond Earrings. The live photos are phone shots on mixed backgrounds; the design's white cards look best with clean studio shots.
6. **Gold bars and coins** never appear: none have been received into stock in Odoo, and they have no photos.
7. **Privacy policy and About us.** Visitors see only a heading on `/privacy` and `/about-us`. The Shopify privacy policy is Shopify's generated template (it describes Shopify's processing), so it cannot be copied as-is; it needs rewriting for Odoo. There is no About text on Shopify to reuse. Each URL also has two hidden theme-demo copies ("consulting, product development…") that can be deleted.
8. **Domain cutover.** When marjaanjewellery.com moves from Shopify: point DNS here, add the domain to nginx and certbot, set Website › Settings › Domain, set `web.base.url`, and update the Shopify-URL redirects you want to keep (Shopify product handles do not exist here).

## Decisions for the owner

- **Web orders vs the counter.** A confirmed web order reserves the piece, and the shop hides it, but the POS checks on-hand stock, not reservations, so the piece can still be sold over the counter. Until the POS learns to block reserved pieces, staff must act on the Pulse alert and set the piece aside.
- **Stale transfer `SM/INT/00010`** (ready since 2026-08-02, never validated) reserves GEF8-0001, GEF8-0061 and GEF8-0128, so they are hidden from the shop. Validate it if the pieces moved, cancel it if not.
- **Indexing before launch.** Search engines may index odoo.marjaanjewellery.com now. Block it in robots.txt until the cutover if that is unwanted.
- **Website salesperson** is Administrator. Web orders are assigned to that user unless changed (Website › Settings).

## Engineering follow-ups

- POS: treat a piece reserved by a confirmed web order as sold (manager override), like the existing re-sale block.
- Shop prices print with `.00` and the `LE` symbol (company currency settings; changing them affects accounting documents too).
- The header menu overlaps the logo at tablet widths (designer CSS in Website › custom head code).
