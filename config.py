"""
MMS Order App — configuration.
All settings come from environment variables so no secrets live in code.
Copy .env.example to .env and fill in your values, OR set env vars in your host.
"""
import os

def _get(name, default=""):
    return os.environ.get(name, default)

# --- Gelato ---
GELATO_API_KEY = _get("GELATO_API_KEY", "")          # from Gelato dashboard > API keys
ORDER_API      = "https://order.gelatoapis.com/v4/orders"
QUOTE_API      = "https://order.gelatoapis.com/v4/orders:quote"
PRODUCT_SEARCH = "https://product.gelatoapis.com/v3/catalogs/{catalog}/products:search"

# Mode controls what happens when someone places an order:
#   dry   -> generate the print files + build the Gelato request, but DO NOT call Gelato (safe, no key needed)
#   draft -> create a DRAFT order in Gelato (shows in your dashboard, NOT charged/printed until you confirm)
#   live  -> create a real order (charged to the card on your Gelato account, printed + shipped)
GELATO_MODE = _get("GELATO_MODE", "dry").lower()

# Public base URL where Gelato can fetch generated print files.
# Locally this is http://localhost:8000 (Gelato can't reach that -> use 'dry').
# When deployed, set this to your public URL, e.g. https://mms-orders.onrender.com
PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# --- Product UIDs (confirm exact codes for your account with find_products.py) ---
# Business cards: single 2-page PDF (front=page1, back=page2) sent as the 'default' file.
CARD_PRODUCT_UID  = _get("CARD_PRODUCT_UID",  "cards_pf_bx_pt_350-gsm-coated-silk_cl_4-4_hor")
# Default flyer product (US Letter). Each flyer can override via data_catalog.json.
FLYER_PRODUCT_UID = _get("FLYER_PRODUCT_UID", "cards_pf_lt_pt_250-gsm-coated-silk_cl_4-4_ver")

SHIPMENT_METHOD = _get("SHIPMENT_METHOD", "normal")   # normal | standard | express
CURRENCY        = _get("CURRENCY", "USD")

# Company info baked onto cards
COMPANY_NAME = "Miller Mechanical Specialties Inc."
COMPANY_URL  = "www.mmsinconline.com"

# Notification (optional): where order summaries are emailed. Left blank = skip.
NOTIFY_EMAIL = _get("NOTIFY_EMAIL", "jtomlin@mmsinconline.com")

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE_DIR, "files")
ASSET_DIR = os.path.join(BASE_DIR, "assets")
