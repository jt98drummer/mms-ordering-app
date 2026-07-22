# CLAUDE.md — MMS Material Ordering Hub

Handoff/context file for continuing this project in Claude Code. Keep it updated as things change.

## What this is
A self-service ordering web app for **Miller Mechanical Specialties (MMS)** with three independent stores, each with its own checkout:
- **Business Cards** — personalized, auto-branded card; company card only; printed by Gelato.
- **Documents** — approved MMS/Signal flyers, line cards, sales guides; company card only; max 25 sheets/doc; printed by Gelato.
- **Swag / Apparel** — cart-based; role-based checkout with an approval safety net; fulfilled by Printful (apparel), Gelato (mug/tote), or an emailed vendor PO (everything else).

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
- **Stripe (not built yet):** `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`.
- **Caps:** `FSE_MGR_AUTO_APPROVE_USD`=250, `EMPLOYEE_MAX_UNITS`=5, `EMPLOYEE_MAX_ORDER_USD`=150, `DOC_MAX_QTY`=25.
- **`ADMIN_TOKEN`** (default `mms-discover`) gates the `/admin/*` diagnostic endpoints.

## How ordering + approvals work
- **Cards / Documents:** checkout on their own page, company card only, receipt auto-emailed to `ACCOUNTING_EMAIL` via Microsoft Graph with orderer/qty/price/purpose/justification.
- **Swag:** cart + role-aware checkout. FSE/managers auto-approve under $250 (over → one approval); employees always route to their manager, then auto-place, capped 5 units/$150; personal card requires a "NOT reimbursable" acknowledgment and creates no accounting receipt; no self-approval. Approvals use HMAC-signed links `/approve/<oid>/<sig>` and `/reject/<oid>/<sig>`.
- **Fulfillment routing** comes from each item's `fulfillment` field in `swag_catalog.json`:
  - `printful` → apparel; `_fulfill_swag()` resolves the variant by color/size and creates a Printful order. Embroidery items (`decoration:"embroidery"`) automatically add a `thread_colors` option.
  - `gelato` → mug (`sw2`) + tote (`sw4`).
  - `vendor` → emailed PO to `VENDOR_EMAIL` (outerwear, FR, hi-vis, promo items).

## Product mappings (in `swag_catalog.json`, verified against live catalogs)
Chosen from MMS's actual buying history (Image Solutions / Fineline decorators; Port Authority polos; Carhartt/North Face outerwear; FR = Bulwark).
- **Printful product IDs:** tee `ap3`=71 (Bella+Canvas 3001) · hoodie `ap8`=146 (Gildan 18500) · crewneck `ap9`=145 (Gildan 18000) · performance polo `ap1`=766 (Under Armour Tech) · cotton polo `ap2`=340 (Port Authority K500) · cap `ap10`=422 (**Richardson 112**) · beanie `ap11`=637 (Richardson 146R cuffed).
- **Gelato UIDs:** mug `sw2` = `mug_product_msz_11-oz_mmat_ceramic-white_cl_4-0` (blue for navy) · tote `sw4` = `bag_product_bsc_tote-bag_bqa_clc_bsi_std-t_bco_natural_bpr_4-0` (black for navy).
- **Vendor PO (Printful can't make these):** softshell `ap5`, quarter-zip `ap6`, vest `ap7` (Carhartt/North Face), hi-vis tee `ap4`, all `sw` promo items (tumbler, water bottle, backpack, cooler, tech, pens, koozie, keychain).
- **Print files:** `/asset/print/mms_logo_dark.png` (all-white, for dark garments) and `mms_logo_light.png` (red script + black wordmark, for light garments). `printful.logo_url_for(color)` picks by garment color (dark colors = navy/black/charcoal/red → white logo).

## Verified working (July 2026, in DRAFT — nothing charged)
- DTG apparel: Bella 3001 tee → Printful draft order created.
- Embroidery: Richardson 112 cap (white thread) → Printful draft order created.
- Gelato: 11oz ceramic mug → Gelato draft order created.
Draft = orders appear in the Printful/Gelato dashboards for review; not produced or charged until confirmed or until modes are flipped to `live`.

## Gotchas / lessons
- **Manual deploy required** (auto-deploy off) — see above.
- Printful catalog: `GET /products?limit=>100` returns HTTP 400; use a plain `GET /products` (returns all ~511). Variants: `GET /products/{id}`.
- Embroidery order items need an `options: [{"id":"thread_colors","value":[...hex]}]`; DTG items don't (Printful auto-fills empty).
- Printful vs Gelato use different recipient shapes — see `printful.create_order()` and `gelato.build_order_payload()`.
- `git` operations failed on the Cowork Windows-mounted folder; clone into a native path to work. (Not an issue in Claude Code on your machine.)

## Open / remaining work
1. **Remove the `/admin/testorder` endpoint** in `app.py` — it's token-gated but can create real (draft) orders; only added for verification.
2. **Delete the test draft orders** (~4 in Printful, 1 in Gelato) from those dashboards.
3. **Reconnect Render ↔ GitHub** so auto-deploy works again.
4. **Set `VENDOR_EMAIL`** so promo/embroidery-vendor POs actually send; optionally `ARCHIVE_EMAIL`.
5. **Stripe personal-card swag checkout** — not built; config seams exist.
6. **SharePoint audit list** — `graph.log_to_sharepoint()` is built and gated; add the `Sites.Selected` app permission, create the list (columns in `.env.example`), set `SP_SITE_ID`/`SP_LIST_ID`.
7. **Add apparel product photos** to the swag storefront (team feedback: "no pictures yet for apparel").
8. **Refinements:** tighten color maps (e.g., "Navy" resolves to Bella "Heather Midnight Navy"); set proper embroidery placements (polo left-chest, cap front, beanie cuff) + per-garment thread palette; scope app-only `Mail.Send` with an Exchange Application Access Policy.
9. **Go live:** flip `PRINTFUL_MODE` and `GELATO_MODE` to `live` when ready for real fulfillment.

## File map
- `app.py` — routes, per-store checkout, `_fulfill_swag()` dispatch, `/admin/*` discovery + `/health`.
- `config.py` — all env-var config + caps.
- `auth.py` — MSAL M365 sign-in; `graph.py` — Graph mail + SharePoint; `printful.py` — Printful client + `resolve_variant()` + `logo_url_for()` + `thread_colors_for()`; `gelato.py` — Gelato client.
- `catalog.py` + `data_catalog.json` — documents; `swag_catalog.json` — apparel/swag + fulfillment mappings.
- `templates/`, `static/`, `assets/` (`assets/print/` = logos), `.github/workflows/keepalive.yml`.
