"""
MMS Order App - configuration.
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
GELATO_MODE    = _get("GELATO_MODE", "dry").lower()   # dry | draft | live

PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

CARD_PRODUCT_UID  = _get("CARD_PRODUCT_UID",  "cards_pf_bx_pt_350-gsm-coated-silk_cl_4-4_hor")
FLYER_PRODUCT_UID = _get("FLYER_PRODUCT_UID", "cards_pf_lt_pt_250-gsm-coated-silk_cl_4-4_ver")

SHIPMENT_METHOD = _get("SHIPMENT_METHOD", "normal")   # normal | standard | express
CURRENCY        = _get("CURRENCY", "USD")

COMPANY_NAME = "Miller Mechanical Specialties Inc."
COMPANY_URL  = "www.mmsinconline.com"
NOTIFY_EMAIL = _get("NOTIFY_EMAIL", "jtomlin@mmsinconline.com")

# --- Flask session secret (set FLASK_SECRET in host env for production) ---
SECRET_KEY = _get("FLASK_SECRET", "dev-only-not-secret-change-me")

# --- Microsoft 365 / Entra ---
# Sign-in uses the delegated auth-code flow; receipts/approvals use app-only Graph mail.
MS_TENANT_ID     = _get("MS_TENANT_ID", "")
MS_CLIENT_ID     = _get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = _get("MS_CLIENT_SECRET", "")       # SECRET -> host env only, never in code
MS_REDIRECT_PATH = _get("MS_REDIRECT_PATH", "/auth/callback")
MS_AUTHORITY     = ("https://login.microsoftonline.com/" + MS_TENANT_ID) if MS_TENANT_ID else ""
MS_SCOPES        = ["User.Read"]                      # delegated sign-in + basic profile
GRAPH_BASE       = "https://graph.microsoft.com/v1.0"

# Auth is ON only when all three Entra values are present; otherwise the app runs
# in DEV mode (synthetic user, role switchable) so the site keeps working.
AUTH_ENABLED = bool(MS_TENANT_ID and MS_CLIENT_ID and MS_CLIENT_SECRET)

# Mailbox that Graph sends receipts/approvals *from* (needs app-only Mail.Send).
MAIL_SENDER = _get("MAIL_SENDER", NOTIFY_EMAIL)
MAIL_MODE   = _get("MAIL_MODE", "auto").lower()       # auto = send if creds else save to outbox

# --- Where accounting receipts go ---
ACCOUNTING_EMAIL  = _get("ACCOUNTING_EMAIL", "accounting@mmsinconline.com")
# Where a manager's own over-limit order escalates (no self-approval).
ESCALATION_EMAIL  = _get("ESCALATION_EMAIL", NOTIFY_EMAIL)

# --- Roles / tiers ---
ROLE_MANAGER, ROLE_FSE, ROLE_EMPLOYEE = "manager", "fse", "employee"
PRIVILEGED_ROLES = (ROLE_MANAGER, ROLE_FSE)           # less-restricted swag tier
ROLE_CLAIM_MAP = {   # Entra App Role "value" -> our tier
    "Manager": ROLE_MANAGER, "manager": ROLE_MANAGER,
    "FSE": ROLE_FSE, "fse": ROLE_FSE, "FieldSalesEngineer": ROLE_FSE,
    "Employee": ROLE_EMPLOYEE, "employee": ROLE_EMPLOYEE,
}
DEFAULT_ROLE = ROLE_EMPLOYEE
DEV_ROLE     = _get("DEV_ROLE", ROLE_EMPLOYEE).lower()  # dev-mode default view

# --- Safety-net caps (all adjustable via env) ---
DOC_MAX_QTY              = int(_get("DOC_MAX_QTY", "25"))          # sheets per document
FSE_MGR_AUTO_APPROVE_USD = float(_get("FSE_MGR_AUTO_APPROVE_USD", "250"))
EMPLOYEE_MAX_UNITS      = int(_get("EMPLOYEE_MAX_UNITS", "5"))
EMPLOYEE_MAX_ORDER_USD  = float(_get("EMPLOYEE_MAX_ORDER_USD", "150"))

# --- Archive / audit mirror ---
ARCHIVE_EMAIL = _get("ARCHIVE_EMAIL", "")            # optional hidden BCC on every receipt (durable mail archive)
SP_SITE_ID    = _get("SP_SITE_ID", "")               # Graph site id for the order-log list
SP_LIST_ID    = _get("SP_LIST_ID", "")               # Graph list id or display name
SP_ENABLED    = bool(SP_SITE_ID and SP_LIST_ID)      # SharePoint mirror on when both set

# --- Stripe (personal-card swag checkout; wired in a later phase) ---
STRIPE_SECRET_KEY      = _get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = _get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = _get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_ENABLED         = bool(STRIPE_SECRET_KEY)

# --- Printful (ALL apparel: print + embroidery) ---
PRINTFUL_API_KEY = _get("PRINTFUL_API_KEY", "")
PRINTFUL_MODE    = _get("PRINTFUL_MODE", "dry").lower()   # dry | draft | live
PRINTFUL_ENABLED = bool(PRINTFUL_API_KEY)

# --- Promo/other swag vendor (emailed PO for items neither Gelato nor Printful makes) ---
VENDOR_EMAIL = _get("VENDOR_EMAIL", "")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
FILES_DIR  = os.path.join(BASE_DIR, "files")
ASSET_DIR  = os.path.join(BASE_DIR, "assets")
OUTBOX_DIR = os.path.join(BASE_DIR, "files", "outbox")
PENDING_DIR = os.path.join(BASE_DIR, "files", "pending")
