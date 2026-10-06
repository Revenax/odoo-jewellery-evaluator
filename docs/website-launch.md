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

## Status after the 2026-10-06 owner decisions

| # | Item | State |
|---|---|---|
| 1 | Payment gateway | **Kashier** module `payment_kashier` built and rehearsed on a copy of prod; installs at the 02:00 Cairo deploy (disabled). Waiting for the owner's keys. |
| 2 | DMARC | Owner: Cloudflare TXT `_dmarc` = `v=DMARC1; p=none; rua=mailto:info@marjaanjewellery.com` |
| 3 | Outgoing email | Done (Zoho, verified 2026-10-06). |
| 4 | Pickup | Sway Mall only, address "Sway Mall, Mohamed Naguib St., New Cairo". |
| 5 | Company address / tax ID | Owner decision: go without. |
| 6 | Photos | Owner to choose: review-based background removal, reshoot, or leave. |
| 7 | Privacy / About | Written (Law 151/2020, Kashier, consent-gated analytics); owner to read once. |
| 8 | Bullion | Banned online (legal): bars, ingots and coins are never mapped or published; their categories are deleted. |
| 9 | SM/INT/00010 | Skipped (owner). |
| 10–11 | Invoice deletion, phantom-piece count | Later (owner). |
| 12 | Indexing | robots.txt `Disallow: /` until the domain cutover. |
| - | POS vs web reservations | Not a gap: the POS check (Pay + server) already uses on-hand minus reserved, so a web-reserved piece needs a manager override. |
| - | Header 992–1280px | CSS fix ships at the 02:00 deploy. |

### Turning Kashier on (owner)
Enter the keys in Odoo, never in chat: Website › Configuration › Payment Providers › Kashier.
1. Merchant ID, Test Payment API Key, Test Secret Key (Kashier dashboard › Integrations). Set State to **Test** and leave it **unpublished**. In Test mode only logged-in staff see it, and Kashier's test cards work.
2. Place one order on the website while logged in, pay with a Kashier test card, and check that the order becomes paid.
3. Enter the Live Payment API Key + Live Secret Key, set State to **Enabled**, and **Publish**.
The webhook (`/payment/kashier/webhook`) is sent with every payment; nothing to set in Kashier's dashboard.

## Blockers (need the owner or an outside account)

1. **Payment gateway.** Only Pay on Site exists, and Odoo allows it only with in-store pickup. A customer who picks delivery reaches payment with no method and cannot finish. Needs a merchant account (Paymob, Fawry, Kashier, Stripe…) and its API keys.
2. **Outgoing email: one password away.** Odoo now sends as `info@marjaanjewellery.com` through Zoho (`scripts/email/configure_email.py`; SPF and DKIM were already set up at Zoho). To switch it on:
   - In Zoho (accounts.zoho.com › Security › App Passwords), create an app password for info@. Zoho's free plan has no SMTP; a paid plan is needed.
   - In Odoo, open Settings › Technical › Outgoing Mail Servers › "Zoho (info@marjaanjewellery.com)", paste the password, and press Test Connection.
   - In Cloudflare DNS, add a TXT record named `_dmarc` with the value `v=DMARC1; p=none; rua=mailto:info@marjaanjewellery.com`. The domain has none, and Gmail/Yahoo treat mail from domains without DMARC as less trustworthy.

   After that, customers get order confirmations, invoices, sign-up and password-reset emails. Replies land in the info@ inbox. Abandoned-cart emails stay off until you turn them on (Website › Settings).
3. **Store addresses and opening hours.** The four pickup contacts have no street, city or hours (Inventory › Configuration › Warehouses › contact; hours via Opening Hours). After entering an address, reset the contact's latitude/longitude to 0 (or press "Compute based on address") so the map shows the right pin. Also: should Black Closet and Abbassi Sagha be pickup points at all?
4. **Company address and tax ID** are empty (Settings › Companies). They print on order confirmations and invoices.
5. **Photos.** Automatic background removal was tested on 6 live photos (2026-10-06, rembg `isnet-general-use`, run locally). Flat-laid bracelets came out like studio shots. Thin chains partly faded, and a ring held in the hand kept the hand. So it would need a per-piece before/after review, not a blind batch. Reshooting on a plain background is still the best fix.
    153 in-stock pieces stay hidden only because they have no photo: 57 Diamond Twin Rings, 51 Center Stones, 17 Diamond Bracelets, 9 Diamond Necklaces, 9 Diamond Rings, 7 Diamond Bands, 2 Gold Earrings, 1 Diamond Earrings. The live photos are phone shots on mixed backgrounds; the design's white cards look best with clean studio shots.
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
- The header menu overlaps the logo at tablet widths (designer CSS in Website › custom head code).
