"""
MMS brand logo variants + which ones suit which garment color.

Four print-ready logos (from the MMS Brand Guide, transparent PNGs in
assets/print/, vectors in assets/print/vector/):
  red_black  Red MMS + black text   -> light garments
  red_white  Red MMS + white text   -> dark garments (keep the red script)
  white      All-white MMS          -> dark garments / one-colour print
  icon_red   Red MMS icon, no text  -> small spots; light or non-red darks

The store lets the shopper pick a logo from the set that suits the garment
colour; the choice flows through checkout to fulfillment (print file +
embroidery thread colours) so the item ships exactly as previewed.
"""
import config

# key -> file (in assets/print), display label, embroidery thread palette
LOGOS = {
    "red_black": {"file": "mms_red_black.png", "label": "Red MMS + black text",  "threads": ["#C8102E", "#000000"]},
    "red_white": {"file": "mms_red_white.png", "label": "Red MMS + white text",  "threads": ["#C8102E", "#FFFFFF"]},
    "white":     {"file": "mms_white.png",     "label": "All-white MMS",          "threads": ["#FFFFFF"]},
    "icon_red":  {"file": "mms_icon_red.png",  "label": "Red MMS icon (no text)", "threads": ["#C8102E"]},
}

# The ink colours each logo actually puts on the garment. A logo is only
# offered when EVERY one of its inks contrasts the garment colour — that's why
# the all-white mark is hidden on white, and the black wordmark on navy.
LOGO_INKS = {
    "red_black": ["#C8102E", "#000000"],
    "red_white": ["#C8102E", "#FFFFFF"],
    "white":     ["#FFFFFF"],
    "icon_red":  ["#C8102E"],
}
# Minimum contrast ratio between an ink and the garment. Lower than the WCAG
# 3:1 text rule on purpose: these are large, bold embroidered/printed marks on
# fabric, not small screen text. 2.0 keeps red-on-navy (2.43) — which reads
# well in the real mockups — while dropping white-on-heather-grey (1.84).
MIN_CONTRAST = 2.0
# Tie-break order when several logos contrast equally well.
_PREFERENCE = ["white", "red_black", "red_white", "icon_red"]

# display colour -> hex chip (for the storefront swatch preview)
COLOR_HEX = {
    "Navy": "#1c2a46", "Black": "#222428", "Grey": "#969ea7", "Gray": "#969ea7",
    "White": "#f4f6f8", "Red": "#c8102e", "Charcoal": "#42484d",
    "Heather Grey": "#b9c0c7", "Heather Charcoal": "#3f4247",
    "Natural": "#d8caaa", "Stone": "#d9d2c2", "Stainless": "#c6ced4",
    "Silver": "#c6ced4", "Navy/Silver": "#1c2a46", "Cool Heather": "#b9c0c7",
    "Steel Grey": "#8a9299", "Sport Grey": "#b9c0c7", "Athletic Heather": "#c7ccd1",
    "Safety Yellow": "#d3db28", "Safety Orange": "#f07616", "Loden": "#4b5320",
}

_RED = {"red"}
_LIGHT = {"white", "grey", "gray", "natural", "stone", "stainless", "silver",
          "safety yellow", "heather grey", "cool heather", "steel grey",
          "sport grey", "athletic heather", "birch", "tan", "sand", "cream"}
_LIGHT_WORDS = ("white", "grey", "gray", "natural", "stone", "silver",
                "birch", "tan", "sand", "cream", "stainless")


def tone(color):
    c = (color or "").strip().lower()
    if c in _RED:
        return "red"
    if c in _LIGHT:
        return "light"
    if any(w in c for w in _LIGHT_WORDS):   # e.g. "heather grey", "steel grey"
        return "light"
    return "dark"                            # navy/black/charcoal/forest/loden/orange...


def _srgb_lum(hex_color):
    """WCAG relative luminance of a hex colour."""
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = out
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = _srgb_lum(a), _srgb_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def logo_contrast(color, key, hexcode=None):
    """Weakest contrast between this logo's inks and the garment colour."""
    bg = hexcode or color_hex(color)
    return min(contrast_ratio(bg, ink) for ink in LOGO_INKS[key])


def logo_options(color, hexcode=None):
    """Every logo that genuinely contrasts this garment, strongest first.

    ALWAYS pass the product's real colour hex when you have it: the same
    display name is a different physical colour per product ("Grey" is
    #5c5e5d on the UA polo but #cececc on the Bella tee), so deciding from
    the display name alone would offer a white logo on a near-white garment.
    """
    scored = [(logo_contrast(color, k, hexcode), -_PREFERENCE.index(k), k) for k in LOGOS]
    ok = [t for t in scored if t[0] >= MIN_CONTRAST]
    if not ok:                                  # never leave an item unbrandable
        ok = [max(scored)]
    return [k for _c, _p, k in sorted(ok, reverse=True)]


def default_logo(color, hexcode=None):
    return logo_options(color, hexcode)[0]


def valid_logo(color, key, hexcode=None):
    """The shopper's pick if it's allowed for this colour, else the default.
    Pass the product's real hex so this agrees with what the storefront showed."""
    opts = logo_options(color, hexcode)
    return key if key in opts else opts[0]


def item_hex(item, color):
    """Real garment hex for a catalog item + display colour (falls back to the
    generic display-name map for non-Printful items)."""
    return ((item or {}).get("color_hex") or {}).get(color) or color_hex(color)


def item_logo_options(item, color):
    return logo_options(color, item_hex(item, color))


def item_valid_logo(item, color, key):
    return valid_logo(color, key, item_hex(item, color))


def label(key):
    return LOGOS.get(key, LOGOS["white"])["label"]


def threads(key):
    """Brand-accurate thread colours (used for display / vendor POs)."""
    return LOGOS.get(key, LOGOS["white"])["threads"]


# Printful embroidery accepts ONLY this fixed thread palette (same list on every
# embroidery product — verified via the catalog `options`). Our brand red
# #C8102E is NOT orderable, so brand colours are snapped to the nearest thread.
PRINTFUL_THREADS = ["#FFFFFF", "#000000", "#96A1A8", "#A67843", "#FFCC00",
                    "#E25C27", "#CC3366", "#CC3333", "#660000", "#333366",
                    "#005397", "#3399FF", "#6B5294", "#01784E", "#7BA35A"]


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def snap_thread(hex_color):
    """Nearest orderable Printful thread to a brand colour (#C8102E -> #CC3333)."""
    r, g, b = _rgb(hex_color)
    return min(PRINTFUL_THREADS,
               key=lambda t: sum((a - c) ** 2 for a, c in zip(_rgb(t), (r, g, b))))


def printful_threads(key):
    """Thread colours for a Printful ORDER — snapped to their allowed palette,
    de-duplicated, order preserved. Sending an unlisted hex is a hard 400."""
    out = []
    for c in threads(key):
        s = snap_thread(c)
        if s not in out:
            out.append(s)
    return out


def logo_path_rot(key):
    """Vertical (90°-rotated) print file — for cylinders like bottles/tumblers,
    where a horizontal logo wraps off the visible face. Generated into
    assets/print/rot/ by gen_products.py rotate."""
    return "/asset/print/rot/" + LOGOS.get(key, LOGOS["white"])["file"]


def item_logo_path(item, key):
    """Print-file path for THIS item — rotated when the product asks for a
    vertical logo (catalog `printful.logo_rotate`)."""
    if (item or {}).get("printful", {}).get("logo_rotate"):
        return logo_path_rot(key)
    return logo_path(key)


def item_logo_url(item, key):
    """Absolute URL of the print file for this item (Printful/Gelato fetch it)."""
    return config.PUBLIC_BASE_URL + item_logo_path(item, key)


def logo_path(key):
    """Site-relative path (works on any host) — use in templates."""
    return "/asset/print/" + LOGOS.get(key, LOGOS["white"])["file"]


def logo_url(key):
    """Absolute public URL — use for Printful/Gelato (their servers fetch it)."""
    return config.PUBLIC_BASE_URL + logo_path(key)


def color_hex(color):
    return COLOR_HEX.get(color, "#8a9299")


def client_logos():
    """Compact map for the frontend: key -> {label, path}."""
    return {k: {"label": v["label"], "path": logo_path(k)} for k, v in LOGOS.items()}
