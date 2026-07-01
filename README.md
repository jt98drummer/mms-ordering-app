# MMS Branded Store — Card & Flyer Ordering App

A working, self-hosted ordering app for **business cards + print documents** that:

- shows a branded storefront (cards form with live preview, document gallery),
- **auto-generates** a print-ready, two-sided business card (personalized front + correct line-card back) from the form,
- places the order through **Gelato's print API** (prints + ships to the employee; the card on your Gelato account is charged automatically),
- logs every order to `orders.csv`.

No vendor has to build anything for you. You run this. The only real cost is the per-item print cost (same as any printer).

---

## 1. Run it locally in 3 commands (safe "dry" mode, no key needed)

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:8000
```

In **dry** mode (the default) the app builds the print files and the exact Gelato
order request, but does **not** contact Gelato — so you can click through and test
everything with zero risk and no API key. Test orders are written to `orders.csv`
and the generated files land in `files/`.

---

## 2. Go live with Gelato (still cheap — pay per card only)

1. Create a free account at **gelato.com**, add your company card under billing,
   and grab an API key (Dashboard → API).
2. Find your exact product codes:
   ```bash
   GELATO_API_KEY=your_key python find_products.py
   ```
   Copy the business-card and flyer UIDs it prints.
3. Copy `.env.example` to `.env` and fill in:
   - `GELATO_API_KEY` = your key
   - `CARD_PRODUCT_UID` / `FLYER_PRODUCT_UID` = the codes from step 2
   - `GELATO_MODE` = `draft` first (creates orders in your Gelato dashboard that you
     confirm by hand), then `live` when you're happy.
   - `PUBLIC_BASE_URL` = your deployed URL (see step 3) — **required for live/draft**,
     because Gelato downloads the print files from this URL.

> Order modes: **dry** (no call) → **draft** (created in Gelato, not charged until you
> confirm) → **live** (charged + printed). Move down this list as you gain confidence.

---

## 3. Deploy so Gelato can reach the print files (free tier)

Gelato fetches the generated PDFs by URL, so the app must be on the public internet
for `draft`/`live`. Easiest free path — **Render.com**:

1. Push this folder to a GitHub repo.
2. On Render: New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app`
4. Add environment variables (same as `.env`), set `PUBLIC_BASE_URL` to the Render URL
   Render gives you (e.g. `https://mms-orders.onrender.com`).
5. Deploy. Visit the URL — you're live.

(Railway, Fly.io, or Azure App Service work the same way.)

---

## 4. How it fits together

```
Employee → /cards or /flyers (browser)
   → POST /api/order/...                     (Flask)
       → card_engine.py builds print-ready PDF   (cards only)
       → file served at /files/<id>.pdf  or  /flyerpdf/<id>
       → gelato.py → Gelato Order API  (charges company card on file)
       → orders.csv  + files/<id>.json (audit trail)
```

## Files

| File | What it does |
|------|--------------|
| `app.py` | Flask routes + order handling |
| `card_engine.py` | Generates the 2-sided card PDF (front + auto-selected back) |
| `gelato.py` | Gelato API client (create order, quote, product search) |
| `catalog.py` / `data_catalog.json` | The flyer/document catalog (your 19 PDFs) |
| `config.py` / `.env` | All settings + secrets (env-based) |
| `find_products.py` | Lists your Gelato product UIDs |
| `templates/`, `static/` | The storefront UI |
| `assets/` | Logo, card backs, flyer PDFs + thumbnails |

## Notes

- **Branding** uses the official MMS logo + palette (navy #1E2D3B, red #C8102E, gold #EDCD1F, Raleway).
- The card back is auto-chosen: **technician → both line cards**, **sales → their territory**.
- Add or remove documents by editing `data_catalog.json` and dropping PDFs in `assets/flyers/`.
- Want a different payment story (let a rep pay their own card)? That's a Stripe add-on — ask and it can be wired in.
