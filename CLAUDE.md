# CLAUDE.md — MMS Material Ordering Hub

Handoff/context file for continuing this project in Claude Code. Keep it updated as things change.

## 👉 START HERE — where we left off (2026-07-31)

**Everything is committed and pushed.** Working tree clean; local `main` == `origin/main` at **`604e3a8`**.

**The immediate next action is waiting on Jayce, not on code.** I published a browsable pick-list of **all 524 orderable Printful products** (search, category filter, tap-to-select, Copy IDs) so he can choose which products to add to the store:
**https://claude.ai/code/artifact/4a8f37c7-dd36-4e01-8c72-abd4a637e189**
When he sends the product IDs → for each one: pull real cost + colours + sizes + **US shippability** (`gen_products.py costs` reports `ship $None` for region-locked items — never publish those), add to `swag_catalog.json`, then `printspec` → `variants` → sync hero → run the three test suites → commit.

⚠️ **A deploy is pending.** He last deployed before the final few commits. Render → **Manual Deploy → Deploy latest commit** (auto-deploy is still disconnected).

**Local dev environment does NOT persist between sessions.** The venv I used lived in the session scratchpad. Recreate one and note that `requirements.txt` pins predate Python 3.14, so install unpinned for local work:
```
python -m venv .venv && .venv/Scripts/python -m pip install flask msal requests stripe reportlab qrcode pillow
```
Keys are in the repo-local `.env` (gitignored): `PRINTFUL_API_KEY`, `GELATO_API_KEY`, `PUBLIC_BASE_URL`. `config.py` loads `.env` automatically (real env vars win).

**Run these before ANY money- or print-related change** (all currently pass):
```
python test_print_accuracy.py                                   # 838 assertions, offline
DATA_DIR=/tmp/r GELATO_MODE=dry PRINTFUL_MODE=dry python test_rules.py
DATA_DIR=/tmp/b MAIL_MODE=off GELATO_MODE=dry PRINTFUL_MODE=dry python test_budget.py
```

## What this is
A self-service ordering web app for **Miller Mechanical Specialties (MMS)**. Three storefronts feed **ONE shared cart** with a single checkout (like any ecommerce site) — the checkout then splits the order by store for fulfillment and applies the role rules:
- **Business Cards** — personalized, auto-branded card; company card only; printed by Gelato.
- **Documents** — approved MMS/Signal flyers, line cards, sales guides; company card only; max 25 sheets each; printed by Gelato.
- **Swag / Apparel** — 27 published items; fulfilled by Printful (all published items), Gelato (mug, unpublished), or an emailed vendor PO (legacy promo items, unpublished).

Stack: **Python / Flask**, server-rendered Jinja templates, deployed on **Render** with **gunicorn**. Microsoft 365 (Entra) sign-in gates the whole app.

## Repo & deploy — READ THIS FIRST
- **Repo:** `github.com/jt98drummer/mms-ordering-app`, branch `main`.
- **Host:** Render web service `mms-self-service-hub` (id `srv-d92v9nkvikkc73b7q4ng`), free tier.
- **Live URL:** https://mms-ordering-app.onrender.com
- **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
- ⚠️ **Auto-deploy is DISCONNECTED.** Render lost GitHub access (build log: "we don't have access to your repo"); it still clones the public repo on a *manual* deploy but does **not** deploy on push. After every push you must go to the Render dashboard → **Manual Deploy → Deploy latest commit**. To fix permanently: Render → Settings → reconnect the GitHub repo, then Auto-Deploy = On Commit.
- Free tier **spins down after ~15 min idle** (~50s cold start). `.github/workflows/keepalive.yml` pings `/health` every 10 min on weekdays via GitHub Actions (free, no effect on Claude usage) to reduce this.

## Local dev
```
pip install -r requirements.txt
python app.py        # http://localhost:8000
```
- With no `MS_*` creds set, the app runs in **DEV mode**: a synthetic user you can re-role via `/setrole/manager|fse|employee` (handy for testing the two swag storefronts).
- To exercise Printful/Gelato locally, put the real keys in a local `.env` (see `.env.example`). (In the Cowork sandbox those APIs were network-blocked, so only the deployed app could reach them — on your own machine via Claude Code that limitation is gone.)

## Configuration (environment variables — live values live in Render, not the repo)
See `.env.example` for the full list. Key ones:
- **Gelato:** `GELATO_API_KEY`, `GELATO_MODE` = `dry|draft|live` (**currently `draft`**), `CARD_PRODUCT_UID`, `FLYER_PRODUCT_UID`.
- **Printful:** `PRINTFUL_API_KEY`, `PRINTFUL_MODE` = `dry|draft|live` (**currently `draft`**). Store id is auto-resolved from the account token.
- **Microsoft 365 / Entra:** `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`. Sign-in turns on only when all three are set. App-registration needs: redirect URI `https://mms-ordering-app.onrender.com/auth/callback`; delegated `User.Read`; **application** `Mail.Send` + `User.Read.All` (admin-consented); App Roles `Manager`/`FSE`/`Employee`.
- **Routing/email:** `ACCOUNTING_EMAIL` (default `accounting@mmsinconline.com`), `NOTIFY_EMAIL`, `ESCALATION_EMAIL`, `VENDOR_EMAIL` (**not set → emailed POs won't send until you add it**), `ARCHIVE_EMAIL` (optional receipt BCC).
- **SharePoint audit (built, inactive):** `SP_SITE_ID`, `SP_LIST_ID` (needs a `Sites.Selected` app permission + a list).
- **Stripe (personal-card swag checkout — built):** `STRIPE_SECRET_KEY` (setting it turns the real charge ON; unset → personal card stays in demo mode), `STRIPE_WEBHOOK_SECRET` (`whsec_…`, required to trust the webhook), `STRIPE_PUBLISHABLE_KEY` (unused server-side — hosted Checkout). Test vs live is the key prefix (`sk_test_`/`sk_live_`); no separate mode flag. Webhook URL: `<PUBLIC_BASE_URL>/api/stripe/webhook`, event `checkout.session.completed`.
- **Budgets & limits (rules rewritten 2026-07-31):** **Employees** need manager approval for EVERY company-card order (cards, documents, swag) — no budget, no spend tracking. **FSEs** need no approval for cards/documents and have a `FSE_BUDGET_USD`=250 swag budget per 2-month calendar period; an order that would exceed the remainder goes to their manager. **Managers** need no approval and have no budget. `EMPLOYEE_BUDGET_USD`=0 means "no budget" (employees are gated by approval instead, so nothing accrues for them). Business-card qty per order: `CARD_MAX_QTY_EMPLOYEE`=100, `CARD_MAX_QTY_FSE`=500 (FSEs **and managers**). `DOC_MAX_QTY`=25 per document. Personal card is available for **swag only** and bypasses approval (NOT reimbursable); cards/documents are always company card. Per-user spend lives in `budget.py` under **`DATA_DIR`** (set to the mounted Render disk `/var/data` — verify with `/admin/budget`).
- **`ADMIN_TOKEN`** (default `mms-discover`) gates the `/admin/*` diagnostics: `/admin/gelato`, `/admin/printful`, and `/admin/budget` (confirms the live budget store path + writability, i.e. that the persistent disk is mounted; `&detail=1` adds per-user spend). ⚠️ Change `ADMIN_TOKEN` from the default in Render since the repo is public.
- **`ROLE_PREVIEW_EMAILS`** (default `jtomlin@mmsinconline.com`) — comma-separated allowlist of signed-in users who get a **private role-preview toggle** (FSE / Employee / Manager) in the top bar to verify the non-FSE safety net. Gated on the real email; a session `role_override` drives `auth.current_user()`'s effective role only for these users (no-op for everyone else). Reset via `/setrole/reset`.

## How ordering + approvals work
- **Cards / Documents:** added to the SHARED cart (no per-store checkout any more), company card only. Receipt auto-emailed to `ACCOUNTING_EMAIL` via Microsoft Graph with orderer/qty/price/purpose/justification. Business-card **qty per order is capped by role** (employee 100 / FSE **and manager** 500), enforced server-side in the checkout + the qty dropdown in `cards.html`. Order context (purpose / for-whom / justification) and the shipping address are collected ONCE in the cart.
- **Swag storefront (ecommerce-style):** `/swag` shows only **published** items (`published:true` in `swag_catalog.json` — currently 27: 12 apparel (incl. WOMEN'S polo + tee, long sleeve, 2 quarter-zips) and 15 tradeshow/event items ev1-ev9 (stickers, koozie, magnet, insulated + stainless tumbler, water bottle, journal, mouse pad, golf towel); the mug and the old vendor promo items stay in the catalog but unpublished) as **preview-only** cards (image, name, price, colour dots) that link to a **product detail page** `/swag/product/<id>` (route `swag_product`, `templates/product.html`). ALL customization lives on the PDP: colour swatches, size, and a colour-aware **logo picker**, with a large hero image that **swaps to the exact pre-rendered colour×logo mockup in real time**. Add-to-cart happens on the PDP. Pre-rendered combos live at `assets/products/variants/<id>__<colour-slug>__<logo-key>.png` (see `gen_products.py variants`); `app.py` builds each item's `img_variants` map from the files that exist.
- **Real costs (item vs shipping) — shown everywhere:** each Printful item's `price` (base size), `price_by_size` (2XL+ genuinely costs more), `ship_first` and `ship_addl` are pulled from the live Printful catalog + a real shipping quote and frozen by **`python gen_products.py costs`**. The storefront, PDP (live per size/qty) and cart all show *item cost + estimated shipping = total MMS pays*. `app.item_unit_cost()` prices the chosen size and `app.estimate_shipping()` mirrors Printful's model (highest first-item rate + additional per extra unit). **The budget is charged goods + shipping** (both are company money). ⚠️ Old prices were guesses and understated reality — the UA polo was listed $28 but costs $50.95. Re-run `costs` whenever Printful pricing changes.
- **Cards / Documents show REAL cost + shipping + delivery** via `gelato.quote_summary()` and `/api/quote/cards` / `/api/quote/documents` (needs `GELATO_API_KEY` and a non-dry `GELATO_MODE`). The quote picks the cheapest shipment method of the same *type* we order with (`SHIPMENT_METHOD`), so quoted shipping matches what's charged; receipts carry the real total. **Documents have their own cart** (`/documents/cart`, localStorage `mms_doccart_v1`). Each store's cart button lives in that store's own **subhead next to the products** (never in the top nav), so the two stores look and behave the same and nobody thinks cards/documents drop into the swag cart; `show_cart` now only gates the swag budget bar — `checkout_documents` takes `items=[{id,qty}]`. Business cards place immediately (no cart); order context is section 1 on both.
- **Swag:** cart + role-aware **budget** checkout (`budget.py`). Company-card orders place immediately while the user is within their 2-month budget (FSE $250 / employee $100); an order that would exceed the remaining budget routes to the manager for one approval, then places. **Money integrity:** the order total is recomputed server-side from `swag_catalog.json` (`_price_items()` — the client's price/name is never trusted; unknown/unpublished items and invalid colour/size/qty are rejected), and the budget is taken via the atomic `budget.try_reserve()`. **Managers are unlimited.** Spend accrues per user on every placed *and* approved company-card order (personal-card + manager orders never accrue). A budget bar (remaining $ + reset date, or "no limit" for managers) shows on every swag page via `base.html`. Personal card requires a "NOT reimbursable" acknowledgment and creates no accounting receipt; no self-approval. Approvals use HMAC-signed links `/approve/<oid>/<sig>` and `/reject/<oid>/<sig>`.
- **Personal-card Stripe flow** (`stripe_pay.py`): when `STRIPE_SECRET_KEY` is set, the personal-card path saves the order as `awaiting_payment` and returns a Stripe **hosted Checkout** URL (no card data touches the app). Fulfillment (`_fulfill_swag`) fires only after payment is confirmed, via `_finalize_paid()` — which is **idempotent** and reached two ways: the `checkout.session.completed` webhook (`/api/stripe/webhook`, signature-verified) and a server-side session re-fetch on the success return (`/swag/pay/return`). Cancel → `/swag/pay/cancel`. With no key set, the path falls back to the original demo behavior (places directly, nothing charged).
- **Fulfillment routing** comes from each item's `fulfillment` field in `swag_catalog.json`:
  - `printful` → apparel; `_fulfill_swag()` resolves the variant by color/size and creates a Printful order. Embroidery items (`decoration:"embroidery"`) automatically add a `thread_colors` option.
  - `gelato` → mug (`sw2`) + tote (`sw4`).
  - `vendor` → emailed PO to `VENDOR_EMAIL` (outerwear, FR, hi-vis, promo items).

## Product mappings (in `swag_catalog.json`, verified against live catalogs)
Chosen from MMS's actual buying history (Image Solutions / Fineline decorators; Port Authority polos; Carhartt/North Face outerwear; FR = Bulwark).
- **Printful product IDs:** tee `ap3`=71 (Bella+Canvas 3001) · hoodie `ap8`=146 (Gildan 18500) · crewneck `ap9`=145 (Gildan 18000) · performance polo `ap1`=766 (Under Armour Tech) · cotton polo `ap2`=340 (Port Authority K500) · cap `ap10`=422 (**Richardson 112**) · beanie `ap11`=637 (Richardson 146R cuffed).
- **Gelato UIDs:** mug `sw2` = `mug_product_msz_11-oz_mmat_ceramic-white_cl_4-0` (blue for navy) · tote `sw4` = `bag_product_bsc_tote-bag_bqa_clc_bsi_std-t_bco_natural_bpr_4-0` (black for navy).
- **Vendor PO (Printful can't make these):** softshell `ap5`, quarter-zip `ap6`, vest `ap7` (Carhartt/North Face), hi-vis tee `ap4`, all `sw` promo items (tumbler, water bottle, backpack, cooler, tech, pens, koozie, keychain).
- **Logos + colour-aware logo picker (`branding.py`):** four MMS brand-guide variants in `assets/print/` (scalable vectors in `assets/print/vector/`): `mms_red_black.png` (light garments), `mms_red_white.png` (dark), `mms_white.png` (dark / all-white), `mms_icon_red.png` (icon, no text). `branding.py` maps a garment colour → tone (light/dark/red) → the logo options the storefront offers, and provides the print-file URL + embroidery thread palette per logo. The swag store lets the shopper **pick a logo per item** (only ones that suit the colour, with a live on-garment swatch); the choice rides through cart → checkout → `_fulfill_swag()` (Printful/Gelato print file + threads, and the vendor PO line) and onto the receipt. `printful.logo_url_for()` now delegates to `branding`.

## Verified working (July 2026, in DRAFT — nothing charged)
- DTG apparel: Bella 3001 tee → Printful draft order created.
- Embroidery: Richardson 112 cap (white thread) → Printful draft order created.
- Gelato: 11oz ceramic mug → Gelato draft order created.
Draft = orders appear in the Printful/Gelato dashboards for review; not produced or charged until confirmed or until modes are flipped to `live`.

## Gotchas / lessons
- **Manual deploy required** (auto-deploy off) — see above.
- Printful catalog: `GET /products?limit=>100` returns HTTP 400; use a plain `GET /products` (returns all ~511). Variants: `GET /products/{id}`.
- **Embroidery orders: the thread option id is PLACEMENT-SPECIFIC** — `thread_colors_chest_left` (polos), `thread_colors_front_large` (cap), plain `thread_colors` (beanie). Sending the generic id where a namespaced one is required is a hard 400 ("option is missing or incorrect"). Frozen per item as `printful.thread_option` by `gen_products.py printspec` (discovered via `printful_mockups.thread_option_for`).
- **Printful accepts only a fixed 15-colour thread palette** (`branding.PRINTFUL_THREADS`). MMS brand red #C8102E is NOT orderable — `branding.printful_threads()` snaps it to the nearest allowed thread (#CC3333). Sending an unlisted hex is a hard 400.
- **`resolve_variant()` must match colours exact-first.** Printful has two-tone colours ("Heather Grey / Black", "Black / Charcoal"). A loose substring match in the WRONG direction (variant colour inside the request) once made the variant "Black" satisfy "Heather Grey / Black" — i.e. ship the wrong-colour cap. Order: exact → alias → request-substring-of-variant only. Validate with the strict check (resolved variant's colour/size must equal what the catalog asked for).
- ⚠️ **Check US shippability before adding a Printful product.** Some are region-locked: AS Colour 4008 (the obvious women's tee pick) ships to **Australia/New Zealand only** and 400s on a US shipping quote. `gen_products.py costs` surfaces this as `ship $None` — never publish an item whose shipping quote failed.
- **No self-serve API vendor sells custom pens / stress balls / pop-sockets / phone wallets.** Printful, Printify, Gelato and Prodigi are print-on-demand only. Printify has no mockup endpoint (breaks the 1:1 rule), Printfection's API cannot place orders, SwagUp only mocks up AFTER an order request, and Safsira (which does have a real pre-order mockup endpoint, `GET /v1/catalog/mockups/`) gates access behind industry approval. Those items must go through the emailed-PO `vendor` route with supplier-supplied imagery.
- Printful vs Gelato use different recipient shapes — see `printful.create_order()` and `gelato.build_order_payload()`.
- `git` operations failed on the Cowork Windows-mounted folder; clone into a native path to work. (Not an issue in Claude Code on your machine.)

## Open / remaining work
Ordered by what matters. Items completed in earlier sessions were removed from this
list once verified — the behaviour they added is documented in the sections above.

### Waiting on Jayce
1. **Pick products from the pick-list** (see START HERE) — then add them following the flow in that section.
2. **Deploy the pending commits** — Render → Manual Deploy → Deploy latest commit.

### Config / ops (no code needed)
3. **Rotate `ADMIN_TOKEN`** in Render — still the default `mms-discover`, and the repo is PUBLIC, so anyone could hit `/admin/budget?...&detail=1` and read per-user spend.
4. **Set `VENDOR_EMAIL`** so emailed vendor POs actually send (code reads it; unset = silently no PO). Optionally `ARCHIVE_EMAIL` for a durable receipt BCC.
5. **Reconnect Render ↔ GitHub** so auto-deploy works again (Settings → reconnect repo → Auto-Deploy: On Commit). Removes the manual-deploy step from every change.
6. **Go live when ready:** flip `PRINTFUL_MODE` and `GELATO_MODE` from `draft` to `live`. Nothing is produced or charged until then.
7. **Activate Stripe** (personal-card swag) — set `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`, create the webhook (`/api/stripe/webhook`, `checkout.session.completed`). Built and tested; dormant until keys exist.
8. **SharePoint audit list** — `graph.log_to_sharepoint()` is built and gated; needs a `Sites.Selected` app permission, the list created (columns in `.env.example`), and `SP_SITE_ID`/`SP_LIST_ID` set.

### Product decisions Jayce may want to revisit
9. **Adidas quarter-zip `ap14` costs $61.20** — one item eats a quarter of an FSE's $250 budget. Consider dropping it, or raising the budget.
10. **Stainless tumbler `ev5` logo is 7.1" tall** (fills the body). Deliberately bold; easy to reduce via `printful.print_fill`.
11. **Apparel front prints sit at 7.7"/9.0"**, not their 12"/14" maximum — a deliberate choice so the tee isn't a full-front print. Say the word to enlarge.
12. **Mug `sw2` is unpublished** — Printful's stand-ins (prod 19/403) are white-bodied mugs, so the wide logo clips on the angled mockup and a "Navy" mug has no coloured print area. Needs real Gelato mug photos before republishing.
13. **Tote `sw4` is unpublished** at Jayce's request (he didn't want it in the store). Real Printful mappings intact if wanted back.

### Known hard limits (don't re-research — already exhausted)
14. **Pens, stress balls, pop-sockets, phone wallets, keychain lights cannot be ordered through ANY self-serve API.** Printful/Printify/Gelato/Prodigi are print-on-demand only; Printify has no mockup endpoint (breaks the 1:1 rule); Printfection's API can't place orders; SwagUp only mocks up after an order request; Safsira has the right API but gates access behind industry approval. These must go through the emailed-PO `vendor` route with supplier-supplied photos. See the Gotchas section.
15. **Budget durability depends on the Render disk.** `DATA_DIR=/var/data` is mounted and verified. A disk binds the service to ONE instance — that's what makes `budget.py`'s file lock sufficient. **Never enable autoscaling / multiple instances without moving the spend store to a database first**, or concurrent orders can overspend. At 65 employees this is nowhere near a concern.
16. **Cards/documents costs are real but per-order**, quoted live from Gelato at checkout; there is no frozen per-item price for them like swag has.

## File map
- `app.py` — routes, per-store checkout, swag storefront + `swag_product` PDP route (`/swag/product/<id>`), per-item `img_variants` map, `_fulfill_swag()` dispatch, `_finalize_paid()` (Stripe), `/admin/*` discovery + `/health`.
- `config.py` — all env-var config + caps.
- `auth.py` — MSAL M365 sign-in; `graph.py` — Graph mail + SharePoint; `printful.py` — Printful client + `resolve_variant()` (logo helpers delegate to `branding`); `gelato.py` — Gelato client; `stripe_pay.py` — Stripe hosted-Checkout client + webhook verify (personal-card swag).
- `branding.py` — the 4 MMS logo variants and a **contrast-driven** logo picker: each logo declares its ink colours and is only offered when EVERY ink clears `MIN_CONTRAST` (2.0) against the garment's REAL hex. ⚠️ Always use `item_logo_options()/item_valid_logo()/item_hex()` (item-aware) — the same display name is a different physical colour per product ("Grey" = #5c5e5d on the UA polo, #cececc on the Bella tee), so deciding from the name alone puts a white logo on a near-white garment. Real hexes are frozen per item as `color_hex` by `gen_products.py printspec`. Also holds print-file URLs and embroidery thread palettes, print-file URLs, embroidery thread palettes, and colour chips (single source of truth for the logo picker + fulfillment).
- `budget.py` — per-user swag budget: bimonthly calendar periods, per-role amounts, and the spend store. **`try_reserve()` is the only safe way to spend** — it check-and-accrues in ONE file-locked step (gunicorn runs multiple workers, so a plain `spent()` then `add_spend()` would let concurrent orders overspend). `release()` refunds a reservation if fulfillment fails; `add_spend()` (locked) is for manager-approved over-budget orders. Writes are fsync'd + atomically replaced.
- **Print accuracy (preview == printed garment):** each Printful item's `printful.print_placement` + `printful.print_position` in `swag_catalog.json` are **frozen** by `gen_products.py printspec` using `printful_mockups.print_spec()` — the same values the storefront mockups were rendered with — and `_fulfill_swag()` sends exactly those on the order. ⚠️ Never send `{"type":"default"}` with no position: Printful then auto-fits the artwork to the WHOLE print area (a 12" tee print where the preview showed 7.7"). Print size per item is `printful.print_fill` (fraction of the print-area width) and was maximised against Printful's real limits. ⚠️ **Cylinders (tumblers/bottle) cannot grow horizontally** — their `default` print area spans the FULL circumference, so a wide logo curves off the visible face and clips. They instead use a **vertical logo** (`print_style:"vertical"` + `logo_rotate:true`) sized by print-area HEIGHT, printed from the pre-rotated files in `assets/print/rot/` (regenerate with the rotate snippet in gen_products history; `branding.item_logo_url()` returns the rotated path so the ORDER and the mockup use the same file). Non-garment goods also set `printful.print_style` in the catalog (`flat` sticker/magnet/mouse pad, `wrap` tumbler/bottle, `cover` journal/towel, `front` tote) because Printful's `default` placement alone can't distinguish a mug wrap from a flat mouse pad. Re-run `printspec` if placements change, and `python test_print_accuracy.py` to verify.
- `test_print_accuracy.py` — 302 offline assertions that the order payload's placement/position/logo/threads match the previewed spec for every published colour×logo combo.
- `test_budget.py` — **run this before changing anything money-related**: `DATA_DIR=/tmp/bt MAIL_MODE=off python test_budget.py`. 30 assertions covering price tampering, invalid/unpublished items, exact budget boundaries, concurrent orders, per-person isolation, approval attribution + double-approval, personal card, refund-on-failure, and period rollover.
- `catalog.py` + `data_catalog.json` — documents; `swag_catalog.json` — apparel/swag + fulfillment mappings + `image` per item.
- ⚠️ The **tote (`sw4`) is unpublished** at the customer's request (they didn't want it in the store); it stays in the catalog with real Printful mappings if it's ever wanted back.
- `gen_swag_tile.py` — rebuilds the homepage Swag tile from REAL product mockups (higher-res border flood-fill cutout, eroded + feathered so there is no jagged white rim; keeps white logo strokes, clears enclosed holes). Uses the official RED icon-only mark from `mms_icon_red.png` (script, no tagline; only transparent margins trimmed) — never typed text, never cropped — and auto-fits the strapline so it can't run under the products. Re-run after adding/re-rendering products.
- `gen_products.py` — image generator: `fallback` (PIL silhouettes), `printful` (per-item hero mockups), and **`variants`** (pre-render every colour×logo combo → `assets/products/variants/`, batched by logo; `MOCKUP_SRC` covers the Gelato mug/tote via Printful imagery); `printful_mockups.py` — Printful Mockup Generator client (printfiles → placement/position → create-task/`generate_multi` → poll → download; 429 backoff).
- `templates/` (incl. `swag.html` = preview storefront, `product.html` = product detail page), `static/`, `assets/` (`assets/print/` = logos + `vector/`, `assets/products/` = hero images + `variants/` = colour×logo mockups, `assets/tiles/` = homepage banners), `.github/workflows/keepalive.yml`.
