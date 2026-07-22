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

# logo options offered per garment tone (first = default/recommended)
OPTIONS = {
    "light": ["red_black", "icon_red"],
    "dark":  ["white", "red_white", "icon_red"],
    "red":   ["white", "red_white"],
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
    return LOGOS.get(key, LOGOS["white"])["threads"]


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
