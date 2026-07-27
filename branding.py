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

# logo options offered per garment tone (first = default/recommended).
# Every option must CONTRAST the garment: red-script logos vanish on a red
# garment, so a red tone only offers the all-white mark.
OPTIONS = {
    "light": ["red_black", "icon_red"],   # red/black on white/grey/natural
    "dark":  ["white", "red_white", "icon_red"],  # white or red on navy/black/charcoal
    "red":   ["white"],                   # only the all-white mark reads on red
}

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


def logo_options(color):
    return OPTIONS[tone(color)]


def default_logo(color):
    return logo_options(color)[0]


def valid_logo(color, key):
    """The shopper's pick if it's allowed for this colour, else the default."""
    return key if key in logo_options(color) else default_logo(color)


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
