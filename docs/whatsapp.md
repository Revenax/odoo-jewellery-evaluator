# Marjaan WhatsApp (Cloud API): setup, operations and lessons

Live since **2026-11-15**. This is the complete record: what exists, how it was set up step by
step, how to operate it, and every trap hit on the way. The code lives in
[whatsapp_gateway/gateway.py](../whatsapp_gateway/gateway.py) (tested in
[tests/test_whatsapp_gateway.py](../tests/test_whatsapp_gateway.py)), the installer is
[scripts/install-whatsapp-gateway.sh](../scripts/install-whatsapp-gateway.sh), and the
operating scripts are in [scripts/whatsapp/](../scripts/whatsapp/).

**Owner decisions:**
- This is **our own integration**, deliberately separate from Odoo's WhatsApp app. Odoo, the ops app and alerts all send through one gateway.
- The number, display name, billing and app all belong to **Marjaan's own business portfolio**, not Revenax's.
- Target: Marjaan name, Marjaan logo, and the blue checkmark (Meta Verified, after business verification).

---

## 1. What exists (IDs)

| Thing | Value |
|---|---|
| Business portfolio | **Marjaan Jewellery**, `144831996807695` (business verification: rejected once, resubmitted, **in review** since 2026-11-15) |
| Meta app | **Marjaan Messaging**, app id `1149149594233355`, **Published**, owned by the Marjaan portfolio |
| Phone number | **+20 10 1148 0480** (`01011480480`), phone number id **`1472843472580652`**, platform CLOUD_API, code verified by SMS |
| Display name | "Marjaan Jewellery" (Meta name review **PENDING_REVIEW** at go-live) |
| WhatsApp account (holds the number) | `1734033171412682` |
| Messaging account (templates and billing) | `1109104548407047`, payment account `2135142760444069`: Visa ···· 9547, USD |
| System user (owns the token) | **Marjaan Messaging**, `61596358001619` (Employee). Assets: app (Develop), the WhatsApp account and the Messaging account (Everything) |
| Profile photo | gold Marjaan mark on navy (see section 7) |
| Privacy policy URL (app) | https://marjaanjewellery.com/policies/privacy-policy |
| Webhook (app subscription) | `https://odoo.marjaanjewellery.com/whatsapp/webhook` |
| Webhook fields | messages, message_template_status_update, phone_number_name_update, account_update, plus the defaults |
| Gateway | systemd `marjaan-whatsapp` on the Odoo box, `127.0.0.1:8076` |
| Secrets | `/etc/marjaan-whatsapp.env` (root 600): `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` |
| Message log | SQLite `/var/lib/marjaan-whatsapp/whatsapp.db`, table `messages` |

Other numbers in the Marjaan portfolio (not used by the gateway):
- **+20 2 2635 7935** (landline): stays on the WhatsApp Business **app** on a phone, linked to the portfolio for Click-to-WhatsApp ads (WhatsApp account `4544775085842112`, Messaging account `459859780545822`, limit 250 customers/24h).
- Two Meta **test** numbers: +1 555-984-0050 and +1 555-804-2365.

Retired test setup under **Revenax Agency** (`124657675550386`), kept for now:
- app "Marjaan Jewellery" `1120768327231037`
- test number +1 555-165-9467
- system user "Marjaan Messaging" `61596401169367`
- WhatsApp account `1780093379958373`, Messaging account `957977993801864`

Its token was replaced on the server by Marjaan's. Revenax Agency's own business verification is **rejected**, which is why production does not live there.

---

## 2. How it works

```
customer WhatsApp ──► Meta Cloud API ──► POST https://odoo.marjaanjewellery.com/whatsapp/webhook
                                           (nginx, `location = /whatsapp/webhook`, access_log off)
                                         ──► gateway 127.0.0.1:8076 (checks X-Hub-Signature-256)
                                         ──► SQLite messages (in / status updates)

Odoo / scripts on the box ──► POST http://127.0.0.1:8076/send ──► Graph API /{phone-id}/messages
```

| Route | Who can reach it | What it does |
|---|---|---|
| `GET /whatsapp/webhook` | public (nginx) | Meta's subscription check: echoes `hub.challenge` when `hub.verify_token` matches |
| `POST /whatsapp/webhook` | public (nginx) | accepted **only** with a valid HMAC-SHA256 of the raw body using the app secret; stores messages and updates statuses (accepted → sent → delivered → read / failed) |
| `POST /send` | loopback only | body `{"to": "...", "text": "..."}` or `{"to", "template", "language", "params": [...]}`, plus `"source"`. `to` is normalised: Egyptian 01… becomes 201… |
| `GET /messages?limit=N` | loopback only | recent messages and their status |
| `GET /health` | loopback only | which secrets are loaded, phone number id, last error |

**The 24-hour rule (Meta, not ours):**
- Free text, documents and images reach a person only within **24 hours of their last message to us**.
- Outside that window, only an **approved template** goes through.
- Business-initiated messages are billed to the Messaging account's card. Replying inside the window is free: 1,000 free service messages per number per month.

---

## 3. Setup, step by step (what was actually done)

### 3a. Test phase (Revenax Agency, now retired)
1. Opened the Revenax app → WhatsApp use case → Step 1 "Try it out" → Continue. This accepted the WhatsApp terms and created a test number.
2. Added a test recipient (owner's number, code sent by WhatsApp) and sent the sample template.
3. Created system user "Marjaan Messaging" and gave it the app and test accounts. The owner generated a never-expiring token and pasted it onto the server (section 9).
4. Built and installed the gateway (`scripts/install-whatsapp-gateway.sh`): systemd service, nginx route, generated verify token.
5. The owner put the app secret on the server and entered the callback URL and verify token in Meta.
6. A signed Meta dashboard test webhook was accepted and stored, proving the pipe end to end.

### 3b. Production (Marjaan portfolio)
1. **Found Marjaan's portfolio:** Revenax only had partner access to Marjaan's Facebook page. The owner added mohamednow25@gmail.com to the "Marjaan Jewellery" portfolio.
2. **Created app "Marjaan Messaging"** in the Marjaan portfolio, use case "Connect with customers through WhatsApp". Meta asked for the Facebook password (the owner entered it).
   An app owned by the business itself needs **no Tech Provider status and no App Review** to message from its own numbers. Revenax's app would have needed both.
3. **Number:** +20 10 1148 0480 was added under the Marjaan portfolio, and its code was confirmed by SMS.
4. **Register was greyed out.** The tooltip said "Number registration and webhook subscription are unavailable for this account now". The cause: the number's WhatsApp account had **no Messaging account**. The fix:
   - Business Settings → WhatsApp accounts → the number → "Add a Messaging account"; or
   - Business Settings → Messaging accounts → Add → pick the WhatsApp account → Finish.

   Then **Register** worked: "Phone number registered successfully".
5. **Payment:** Messaging account → Payment Settings → the owner added the Visa (USD). Still open: the "Verify" card prompt and the VAT tax-info banner.
6. **System user "Marjaan Messaging"** in the Marjaan portfolio. The owner assigned the app (Develop), the WhatsApp account and the Messaging account (Everything); my click was blocked by the permission settings. The owner then generated a token: app Marjaan Messaging, expiration Never, scopes `whatsapp_business_messaging` and `whatsapp_business_management`. They pasted it and the app secret onto the server.
7. **Gateway pointed at the number:** `WHATSAPP_PHONE_NUMBER_ID=1472843472580652`, then restarted.
8. **Webhook and subscription by API.** These ran on the server; the app token is `app_id|app_secret` and is never printed.
   - `POST /{app-id}/subscriptions` with object `whatsapp_business_account`, the callback URL, the verify token and the fields
   - `POST /{messaging-account-id}/subscribed_apps` with the system-user token
9. **Profile photo** uploaded by API (section 7).
10. **Publish:** set the privacy policy URL (App settings → Basic), then Publish → **Published**. Until then Meta delivers only dashboard test webhooks: **no real messages reach an unpublished app**.
11. **Live test:**
    - The owner messaged the number; the webhook stored it.
    - The gateway replied with a personalised text (status **sent**).
    - It then sent the latest invoice, MJ-1617, as a PDF document with a post-order caption (status **delivered**). This was a simulation, sent to the owner's own number only.

---

## 4. Daily operations

On the Odoo box (`ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com`):

```bash
curl -s http://127.0.0.1:8076/health                       # secrets loaded? last error?
curl -s "http://127.0.0.1:8076/messages?limit=20"          # recent in/out with status
sudo journalctl -u marjaan-whatsapp -n 50 --no-pager       # gateway log (no secrets in it)
sudo systemctl restart marjaan-whatsapp                    # after changing /etc/marjaan-whatsapp.env
```

Send a text (only inside the 24-hour window):
```bash
curl -s -X POST http://127.0.0.1:8076/send -H 'Content-Type: application/json' \
  -d '{"to":"01063864994","text":"Hello from Marjaan","source":"manual"}'
```

Send an approved template (any time):
```bash
curl -s -X POST http://127.0.0.1:8076/send -H 'Content-Type: application/json' \
  -d '{"to":"01063864994","template":"order_confirmation","language":"en","params":["Mohamed","MJ-1617"],"source":"odoo"}'
```

Send an invoice PDF with a caption (only inside the 24-hour window, until a document template exists):
```bash
scripts/ops/run_odoo.sh scripts/whatsapp/render_invoice_pdf.py INV=MJ-1617      # from the Mac: renders /tmp/wa_invoice.pdf on the box
# on the box: write the caption to /tmp/caption.txt, then
sudo TO=01063864994 FILE=/tmp/wa_invoice.pdf FILENAME="Marjaan Invoice MJ-1617.pdf" \
     CAPTION_FILE=/tmp/caption.txt python3 send_document.py
```

The post-order caption used on 2026-11-15:
> Dear ريهام شريف, Thank you for choosing Marjaan Jewellery ✨ Your order is confirmed and
> fully paid. • 18K Gold Necklace · 12.16 g • 18K Gold Bands · 2.25 g • 18K Gold Bracelet ·
> 6.02 g. Total: 121,900 EGP. Invoice MJ-1617 is attached for your records. We hope you love
> wearing your new pieces. For sizing, cleaning or anything at all, simply reply to this
> message. With love, Marjaan Jewellery · مرجان

Piece titles come from `product.template.website_title`. Line totals come from the invoice.

---

## 5. Gateway install, update and secrets

- Install or update from the Mac: `scripts/install-whatsapp-gateway.sh`. It copies `gateway.py` to `/opt/marjaan-whatsapp/` and writes the systemd unit (runs as `odoo`, `ProtectSystem=strict`, `MemoryMax=96M`). It also adds the nginx route with `access_log off` (backing up the site file and running `nginx -t`), generates `WHATSAPP_VERIFY_TOKEN` once, and scrubs any verify token from nginx logs.
- **Server-side, NOT part of the deploy.** Re-run it if the box is rebuilt, and restore `/etc/marjaan-whatsapp.env` (token and app secret come from the owner again).
- Tests: `pytest tests/test_whatsapp_gateway.py` runs in CI, and the gateway dir is ruff-linted.

---

## 6. Templates (needed for messages Marjaan starts first)

**Why:** WhatsApp lets a business message someone first **only with a template Meta has approved** (anti-spam). Free text and files work only within 24 hours of the customer's last message.

**Submitted 2026-11-15, all APPROVED the same day.** English only, wording approved by the owner. Messaging account `1109104548407047`.

All were submitted as UTILITY. **Meta re-categorised `welcome_contact` to MARKETING**: a message not tied to a specific order, payment or pickup counts as promotional. Marketing costs more per message, the customer can opt out, and Meta may limit how often marketing reaches a person. The other 4 stayed UTILITY.

The script is [scripts/whatsapp/submit_templates.py](../scripts/whatsapp/submit_templates.py). It is idempotent and skips templates that already exist. `--status` lists the approval state; a document header needs an example PDF, set with `EXAMPLE_PDF=`.

| Name | Header | Body ({{n}} = filled per customer) |
|---|---|---|
| `order_confirmation` | invoice PDF | Dear {{1}}, thank you for shopping at Marjaan Jewellery ✨ Your order {{2}} is confirmed. Total: {{3}} EGP. Your invoice is attached for your records. For sizing, cleaning or any help, simply reply to this message. |
| `order_ready_pickup` | none | Hi {{1}}, good news! Your order {{2}} is ready for pickup at Marjaan {{3}}. We look forward to seeing you. |
| `payment_received` | none | Dear {{1}}, we have received your payment of {{2}} EGP for {{3}}. Thank you for choosing Marjaan Jewellery. |
| `buyback_receipt` | receipt PDF | Dear {{1}}, thank you for your trust. We have bought your piece ({{2}}) for {{3}} EGP. Your receipt is attached. |
| `welcome_contact` | none | Hi {{1}}, this is Marjaan Jewellery. Thank you for visiting us. This is our official WhatsApp; reply here anytime for prices, new pieces or help with an order. |

- **Arabic versions** were drafted and dropped (owner decision). If they are ever added, use gender-neutral "عزيزنا العميل {{1}}".
- **Promotions** need separate MARKETING templates: they cost more and customers can opt out.
- A template stays UTILITY only if it is about a specific transaction (it names an order, a payment or a pickup). Anything general ("thanks for visiting", "new pieces") becomes MARKETING.

To add or edit a template:
1. Change `TEMPLATES` in the script.
2. Copy the script to the box and run it. An already-approved template cannot be edited in place: create a new name.

**Send an approved template (with or without a document header):** [scripts/whatsapp/send_template.py](../scripts/whatsapp/send_template.py), run on the box. Templates may be sent at any time, with no 24-hour window:

```bash
scripts/ops/run_odoo.sh scripts/whatsapp/render_invoice_pdf.py INV=MJ-1619       # from the Mac
# on the box:
sudo TO=01007709545 TEMPLATE=order_confirmation PARAMS='["Name","MJ-1619","13,500"]' \
     FILE=/tmp/wa_invoice.pdf FILENAME="Marjaan Invoice MJ-1619.pdf" python3 send_template.py
sudo rm -f /tmp/wa_invoice.pdf
```

First business-initiated message: 2026-11-15, `order_confirmation` with MJ-1619 to +20 100 770 9545, **delivered**. The owner chose to send MJ-1619 although that number belongs to a different customer (عزة احمد), as a test.

**Privacy rule:** before sending an invoice, check that the recipient's number is the invoice customer's (`res.partner.phone`). Never send one customer's invoice to another customer unless the owner explicitly says so.

Under the hood, sending an approved template with a document header is a Graph call to `/{phone-id}/messages`. In the template components, set `{"type":"header","parameters":[{"type":"document","document":{"id": <media id>, "filename": "..."}}]}` plus the body parameters. The gateway's `/send` covers text-only templates; document templates go through the Graph call, until the Odoo hook is built.

---

## 7. Profile (name, logo, details)

- **Display name** "Marjaan Jewellery" is under Meta review. The `phone_number_name_update` webhook and `GET /{phone-id}?fields=name_status` show the result.
- **Profile photo** comes from `scripts/whatsapp/set_profile_photo.py` (resumable upload, then `profile_picture_handle`). The image is `marjaan_branding/static/img/icon-512x512.png` (gold mark) scaled to 86% on a 640×640 navy `#0f1138` square. WhatsApp crops photos to a circle.
- Website: https://www.marjaanjewellery.com/. Category: Shopping and Retail (vertical RETAIL).
- Description, address, email and hours are empty. The **owner** writes the wording, set by `POST /{phone-id}/whatsapp_business_profile`.

---

## 8. Path to the blue checkmark

1. Business verification of the Marjaan portfolio must **pass**. It was rejected once ("can't determine the portfolio belongs to an actual business") and is now in review. If it fails again:
   - upload the commercial register and tax card in the exact legal name "Marjaan Jewellery";
   - match the website domain, address and phone;
   - the portfolio has **no business phone** set, so add one.
2. The display name gets approved.
3. **Meta Verified** for WhatsApp (Business Settings → Meta Verified): a paid monthly subscription the owner buys. It gives the blue checkmark.
4. Verification also raises limits: more than 2 numbers, higher messaging tiers.

---

## 9. Secrets: how to put them on the server (never in chat or files)

zsh (macOS) syntax. The value is never echoed. The commands below are the token and app secret versions:

```bash
read -rs "T?Paste WhatsApp token: " && echo && printf '%s' "$T" | ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com 'sudo bash -c "T=\$(cat); sed -i /^WHATSAPP_TOKEN=/d /etc/marjaan-whatsapp.env; printf \"WHATSAPP_TOKEN=%s\n\" \"\$T\" >> /etc/marjaan-whatsapp.env; systemctl restart marjaan-whatsapp; echo saved"' ; unset T
```

```bash
read -rs "S?Paste app secret: " && echo && printf '%s' "$S" | ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com 'sudo bash -c "S=\$(cat); sed -i /^WHATSAPP_APP_SECRET=/d /etc/marjaan-whatsapp.env; printf \"WHATSAPP_APP_SECRET=%s\n\" \"\$S\" >> /etc/marjaan-whatsapp.env; systemctl restart marjaan-whatsapp; echo saved"' ; unset S
```

Check without revealing: compare the token length to the count of `EAA` occurrences (a double paste shows two), then `GET /{phone-id}` with only selected fields printed.

**Rotate a token:** System users → Marjaan Messaging → Revoke tokens → Generate token → run the command above.

---

## 10. Lessons and traps (do not relearn these)

1. **Never print raw Graph API error bodies.** A "Malformed access token" error **echoes the token**. That happened once (2026-11-15) and the token had to be revoked. Print only `error.code` / `error_subcode`. `safe_graph_error` and all the scripts scrub `EAA…`.
2. **Meta's verify GET carries the verify token in the query string**, so nginx logged it. The webhook route now has `access_log off`, and the installer scrubs old lines (`hub.verify_token` and `hub_verify_token`).
3. **zsh `read -p` doesn't prompt** ("no coprocess"). Use `read -rs "VAR?Prompt: "`.
4. **A pasted token can come out doubled** (two `EAA`, 406 characters instead of about 200, rejected as malformed). Check the length and the `EAA` count.
5. **Meta's 2026 model splits two accounts:**
   - the **WhatsApp account** holds the phone number;
   - the **Messaging account** holds templates and billing.

   A system user needs **both**. Graph calls on the WhatsApp account id may fail with subcode 2388339; use the phone number id.
6. **Register is greyed out until a Messaging account is linked** to the number's WhatsApp account (section 3b step 4).
7. **An unverified business may hold only 2 numbers.** Verified: 20.
8. **Unpublished app means no real messages.** Only dashboard "Test" webhooks arrive. Publishing needs just a privacy policy URL for a business-owned app.
9. **App ownership matters.**
   - An app owned by another business (e.g. Revenax's) needs Tech Provider status plus App Review to message a client's number. Both require a verified business, and Revenax's verification was rejected.
   - Coexistence (WhatsApp Business app and API on one number) only exists through the partner flow, which needs a Tech Provider. So the landline stays on the app until Marjaan or Revenax is verified.
10. **System user names cannot contain "WhatsApp".**
11. **Business-scoped user IDs (usernames rollout, 2026):**
    - Inbound messages may carry `from_user_id: "EG.1125…"` and **no phone number**; contacts carry `user_id`.
    - The gateway accepts both since `ffab9e4`.
    - Replying by the person's phone number still works inside their 24-hour window.
12. **CAPTCHA and password prompts in Meta's UI are for the owner.** So are card details and one-time codes. The permission settings also blocked my assigning assets to the system user; the owner clicked those.
13. **Several accounts named "Marjaan Jewellery" exist** and the asset picker does not search by ID. Assign from the account's own page, where the number is shown.

---

## 11. Open items

- [ ] Display name approval ("Marjaan Jewellery").
- [ ] Business verification (in review), then Meta Verified (blue tick, the owner subscribes).
- [ ] Card "Verify" and VAT tax info on the billing page (owner).
- [x] Templates: 5 approved 2026-11-15 (4 UTILITY; `welcome_contact` moved to MARKETING by Meta). Decide whether to keep `welcome_contact`.
- [ ] Odoo hook: on POS order or invoice post, call `127.0.0.1:8076/send` with the template and the invoice PDF. Customer mobile is needed on the partner.
- [ ] Business profile text (about, address, hours, email): owner's wording.
- [ ] Landline +20 2 2635 7935: coexistence after verification, or keep it on the app.
- [ ] Retire the Revenax test setup (app 1120768327231037, test number, system user 61596401169367). Ask first.
