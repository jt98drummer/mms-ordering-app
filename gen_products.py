"""
Generate branded product images for the swag storefront -> assets/products/<id>.png
(served at /asset/products/<id>.png; wired into swag_catalog.json as each item's
"image", with the SVG icon as a graceful fallback).

Two sources, matching the agreed hybrid:
  * Printful items (the 7 apparel pieces Printful makes): photorealistic mockups
    via the Printful Mockup Generator (`build_printful`) — the SAME MMS logo print
    file fulfillment uses, composited onto a real garment photo. Needs
    PRINTFUL_API_KEY (read from .env). Overwrites the generated fallback.
  * Everyone else (promo + drinkware + vendor apparel): clean, on-brand generated
    product images (`build_fallbacks`) drawn with PIL — colored product silhouette
    on a soft studio backdrop with the MMS logo placed like it prints. No key.

Usage:
  python gen_products.py            # fallbacks for all, then Printful mockups if key present
  python gen_products.py fallback   # only the generated PIL images (no key needed)
  python gen_products.py printful    # only the Printful mockups (needs key)
  python gen_products.py catalog     # only (re)write the "image" field into the catalog
"""
import os, sys, json
from PIL import Image, ImageDraw, ImageFilter

APP = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(APP, "assets", "products"); os.makedirs(OUT, exist_ok=True)
PRINT_DIR = os.path.join(APP, "assets", "print")
CATALOG = os.path.join(APP, "swag_catalog.json")


def _load_env(path):
    if os.path.exists(path):
        for raw in open(path):
            s = raw.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env(os.path.join(APP, ".env"))

FINAL = 820                     # output px (square)
SS = 2                          # supersample factor
W = FINAL * SS                  # working canvas px

# Brand-ish product base colors (RGB).
COLORS = {
    "Navy": (28, 42, 70), "Black": (34, 36, 40), "Red": (196, 22, 48),
    "White": (245, 247, 249), "Gray": (150, 158, 167), "Charcoal": (66, 70, 77),
    "Natural": (216, 202, 170), "Safety Yellow": (211, 219, 40),
    "Safety Orange": (240, 118, 22), "Stainless": (198, 205, 212),
    "Silver": (200, 205, 212), "Navy/Silver": (28, 42, 70),
}
DARK = {"navy", "black", "charcoal", "red", "navy/silver", "safety orange"}

# id -> silhouette shape
SHAPE = {
    "ap1": "polo", "ap2": "polo", "ap3": "tee", "ap4": "tee", "ap5": "jacket",
    "ap6": "jacket", "ap7": "vest", "ap8": "hoodie", "ap9": "hoodie",
    "ap10": "cap", "ap11": "beanie",
    "sw1": "tumbler", "sw2": "mug", "sw3": "bottle", "sw4": "tote",
    "sw5": "backpack", "sw6": "cooler", "sw7": "gadget", "sw8": "gadget",
    "sw9": "gadget", "sw10": "notebook", "sw11": "pen", "sw12": "koozie",
    "sw13": "keychain",
}
# shape -> (logo width as fraction of sprite width, (cx frac, cy frac))
PLACE = {
    "polo": (0.20, (0.37, 0.44)), "tee": (0.42, (0.50, 0.48)),
    "jacket": (0.19, (0.37, 0.42)), "vest": (0.19, (0.37, 0.42)),
    "hoodie": (0.40, (0.50, 0.54)), "cap": (0.36, (0.50, 0.47)),
    "beanie": (0.34, (0.50, 0.58)), "mug": (0.40, (0.42, 0.52)),
    "tumbler": (0.40, (0.50, 0.52)), "bottle": (0.44, (0.50, 0.55)),
    "tote": (0.46, (0.50, 0.54)), "backpack": (0.30, (0.50, 0.44)),
    "cooler": (0.42, (0.50, 0.50)), "gadget": (0.46, (0.50, 0.50)),
    "notebook": (0.44, (0.52, 0.50)), "pen": (0.26, (0.50, 0.47)),
    "koozie": (0.44, (0.50, 0.50)), "keychain": (0.36, (0.50, 0.42)),
}


def shade(c, f):
    return tuple(max(0, min(255, int(x * f))) for x in c[:3])


def spr(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def rr(d, box, radius, fill, outline=None, width=0):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


# ---------------- silhouettes (drawn large, pasted, downscaled) ----------------
def s_tee(c, name):
    w, h = 1160, 1000; im, d = spr(w, h); dk = shade(c, 0.80); ln = shade(c, 0.62)
    d.polygon([(120, 150), (360, 110), (455, 430), (250, 500)], fill=dk, outline=ln, width=5)
    d.polygon([(w - 120, 150), (w - 360, 110), (w - 455, 430), (w - 250, 500)], fill=dk, outline=ln, width=5)
    rr(d, [325, 120, w - 325, h - 40], 55, c, ln, 5)
    cx = w // 2
    d.pieslice([cx - 150, 70, cx + 150, 300], 18, 162, fill=(0, 0, 0, 0))
    d.arc([cx - 150, 70, cx + 150, 300], 18, 162, fill=ln, width=6)
    return im


def s_polo(c, name):
    w, h = 1120, 1000; im, d = spr(w, h); dk = shade(c, 0.80); ln = shade(c, 0.60)
    d.polygon([(130, 160), (360, 120), (450, 440), (255, 505)], fill=dk, outline=ln, width=5)
    d.polygon([(w - 130, 160), (w - 360, 120), (w - 450, 440), (w - 255, 505)], fill=dk, outline=ln, width=5)
    rr(d, [330, 130, w - 330, h - 40], 55, c, ln, 5)
    cx = w // 2
    d.polygon([(cx - 120, 150), (cx, 360), (cx + 120, 150), (cx, 120)], fill=(0, 0, 0, 0))
    d.polygon([(cx - 120, 150), (cx - 30, 340), (cx, 150)], fill=dk, outline=ln, width=4)
    d.polygon([(cx + 120, 150), (cx + 30, 340), (cx, 150)], fill=dk, outline=ln, width=4)
    d.line([(cx, 250), (cx, 470)], fill=ln, width=5)
    for i in range(2):
        d.ellipse([cx - 8, 300 + i * 70, cx + 8, 316 + i * 70], fill=ln)
    return im


def s_jacket(c, name):
    w, h = 1140, 1020; im, d = spr(w, h); dk = shade(c, 0.78); ln = shade(c, 0.58)
    d.polygon([(120, 170), (350, 120), (450, 470), (250, 540)], fill=dk, outline=ln, width=5)
    d.polygon([(w - 120, 170), (w - 350, 120), (w - 450, 470), (w - 250, 540)], fill=dk, outline=ln, width=5)
    rr(d, [330, 140, w - 330, h - 40], 45, c, ln, 5)
    cx = w // 2
    d.polygon([(cx - 110, 150), (cx - 55, 300), (cx + 55, 300), (cx + 110, 150)], fill=dk, outline=ln, width=4)
    d.line([(cx, 175), (cx, h - 55)], fill=ln, width=8)
    d.rectangle([cx - 8, 175, cx + 8, 300], fill=shade(c, 0.9))
    return im


def s_vest(c, name):
    w, h = 1020, 1000; im, d = spr(w, h); ln = shade(c, 0.58); dk = shade(c, 0.80)
    rr(d, [250, 150, w - 250, h - 40], 45, c, ln, 5)
    d.polygon([(250, 175), (250, 620), (150, 470), (170, 210)], fill=dk, outline=ln, width=4)
    d.polygon([(w - 250, 175), (w - 250, 620), (w - 150, 470), (w - 170, 210)], fill=dk, outline=ln, width=4)
    cx = w // 2
    d.polygon([(cx - 100, 160), (cx - 50, 300), (cx + 50, 300), (cx + 100, 160)], fill=dk, outline=ln, width=4)
    d.line([(cx, 185), (cx, h - 55)], fill=ln, width=8)
    return im


def s_hoodie(c, name):
    w, h = 1180, 1040; im, d = spr(w, h); dk = shade(c, 0.78); ln = shade(c, 0.58)
    d.polygon([(110, 210), (360, 165), (455, 500), (250, 560)], fill=dk, outline=ln, width=5)
    d.polygon([(w - 110, 210), (w - 360, 165), (w - 455, 500), (w - 250, 560)], fill=dk, outline=ln, width=5)
    rr(d, [325, 190, w - 325, h - 40], 50, c, ln, 5)
    cx = w // 2
    d.chord([cx - 210, 90, cx + 210, 340], 0, 180, fill=dk, outline=ln, width=5)
    d.chord([cx - 150, 150, cx + 150, 330], 0, 180, fill=shade(c, 0.6))
    rr(d, [cx - 250, h - 360, cx + 250, h - 150], 30, dk, ln, 4)   # pocket
    d.ellipse([cx - 150, 300, cx - 128, 322], fill=ln); d.ellipse([cx + 128, 300, cx + 150, 322], fill=ln)
    d.line([(cx - 139, 311), (cx - 120, 470)], fill=(238, 238, 238), width=8)
    d.line([(cx + 139, 311), (cx + 120, 470)], fill=(238, 238, 238), width=8)
    return im


def s_cap(c, name):
    w, h = 980, 720; im, d = spr(w, h); ln = shade(c, 0.6); dk = shade(c, 0.82)
    d.chord([80, 40, w - 80, 620], 180, 360, fill=c, outline=ln, width=5)
    d.ellipse([120, 300, w - 60, 560], fill=dk, outline=ln, width=5)   # brim
    d.line([(w // 2, 70), (w // 2, 330)], fill=ln, width=4)
    d.ellipse([w // 2 - 12, 60, w // 2 + 12, 84], fill=ln)
    return im


def s_beanie(c, name):
    w, h = 860, 780; im, d = spr(w, h); ln = shade(c, 0.6); dk = shade(c, 0.80)
    d.pieslice([90, 70, w - 90, h - 40], 180, 360, fill=c, outline=ln, width=5)
    rr(d, [90, h - 230, w - 90, h - 40], 40, dk, ln, 5)               # cuff
    for x in range(180, w - 150, 70):
        d.line([(x, 120), (x + 30, h - 250)], fill=shade(c, 0.9), width=6)
    return im


def s_mug(c, name):
    w, h = 900, 780; im, d = spr(w, h); ln = shade(c, 0.6)
    rr(d, [190, 120, 660, h - 90], 60, c, ln, 5)
    d.arc([560, 250, 800, 560], -80, 90, fill=ln, width=42)          # handle
    d.ellipse([190, 95, 660, 175], fill=shade(c, 1.08), outline=ln, width=5)
    return im


def s_tumbler(c, name):
    w, h = 560, 1000; im, d = spr(w, h); ln = shade(c, 0.6)
    d.polygon([(150, 210), (w - 150, 210), (w - 185, h - 70), (185, h - 70)], fill=c, outline=ln, width=5)
    rr(d, [150, 70, w - 150, 220], 40, shade(c, 0.86), ln, 5)        # lid
    rr(d, [175, 40, w - 175, 110], 30, shade(c, 0.94), ln, 4)
    return im


def s_bottle(c, name):
    w, h = 520, 1040; im, d = spr(w, h); ln = shade(c, 0.6)
    rr(d, [150, 250, w - 150, h - 70], 70, c, ln, 5)
    rr(d, [210, 120, w - 210, 270], 20, shade(c, 0.9), ln, 4)        # neck
    rr(d, [185, 40, w - 185, 150], 26, shade(c, 0.82), ln, 5)        # cap
    return im


def s_tote(c, name):
    w, h = 900, 880; im, d = spr(w, h); ln = shade(c, 0.6)
    rr(d, [150, 250, w - 150, h - 50], 26, c, ln, 5)
    d.arc([250, 60, 470, 420], 160, 20, fill=ln, width=26)          # handles
    d.arc([w - 470, 60, w - 250, 420], 160, 20, fill=ln, width=26)
    return im


def s_backpack(c, name):
    w, h = 820, 1020; im, d = spr(w, h); ln = shade(c, 0.6); dk = shade(c, 0.82)
    rr(d, [160, 150, w - 160, h - 60], 90, c, ln, 5)
    rr(d, [230, 470, w - 230, h - 150], 50, dk, ln, 4)              # front pocket
    d.arc([250, 90, 400, 360], 180, 360, fill=ln, width=22)        # straps
    d.arc([w - 400, 90, w - 250, 360], 180, 360, fill=ln, width=22)
    rr(d, [w // 2 - 30, 120, w // 2 + 30, 210], 16, dk)            # top handle
    return im


def s_cooler(c, name):
    w, h = 1020, 820; im, d = spr(w, h); ln = shade(c, 0.6); dk = shade(c, 0.82)
    rr(d, [140, 300, w - 140, h - 60], 50, c, ln, 5)
    rr(d, [120, 190, w - 120, 340], 40, dk, ln, 5)                  # lid
    d.arc([w // 2 - 120, 90, w // 2 + 120, 260], 180, 360, fill=ln, width=22)  # handle
    return im


def s_gadget(c, name):
    w, h = 900, 640; im, d = spr(w, h); ln = shade(c, 0.6)
    rr(d, [180, 120, w - 180, h - 120], 60, c, ln, 5)
    d.ellipse([w // 2 - 70, h // 2 - 70, w // 2 + 70, h // 2 + 70], outline=shade(c, 1.2), width=8)
    return im


def s_notebook(c, name):
    w, h = 820, 1020; im, d = spr(w, h); ln = shade(c, 0.6); dk = shade(c, 0.82)
    rr(d, [190, 110, w - 150, h - 90], 26, c, ln, 5)
    d.rectangle([190, 110, 250, h - 90], fill=dk)                   # spine
    d.rectangle([w - 250, 130, w - 210, h - 110], fill=shade(c, 0.7), width=0)  # elastic band
    return im


def s_pen(c, name):
    w, h = 980, 980; im, d = spr(w, h); ln = shade(c, 0.55)
    d.polygon([(150, 760), (240, 700), (760, 220), (700, 160)], fill=c, outline=ln, width=4)
    d.polygon([(150, 760), (200, 730), (170, 700)], fill=shade(c, 0.5))   # tip
    d.polygon([(700, 160), (760, 220), (820, 150), (770, 110)], fill=shade(c, 0.85), outline=ln, width=3)  # clip end
    return im


def s_koozie(c, name):
    w, h = 660, 820; im, d = spr(w, h); ln = shade(c, 0.6)
    d.polygon([(180, 190), (w - 180, 190), (w - 150, h - 90), (150, h - 90)], fill=c, outline=ln, width=5)
    d.ellipse([150, 150, w - 150, 240], fill=shade(c, 0.86), outline=ln, width=4)
    return im


def s_keychain(c, name):
    w, h = 660, 900; im, d = spr(w, h); ln = shade(c, 0.55)
    d.ellipse([w // 2 - 110, 90, w // 2 + 110, 310], outline=shade(c, 0.8), width=34)  # ring
    rr(d, [w // 2 - 150, 300, w // 2 + 150, h - 90], 40, c, ln, 5)    # fob
    return im


SHAPES = {
    "tee": s_tee, "polo": s_polo, "jacket": s_jacket, "vest": s_vest,
    "hoodie": s_hoodie, "cap": s_cap, "beanie": s_beanie, "mug": s_mug,
    "tumbler": s_tumbler, "bottle": s_bottle, "tote": s_tote,
    "backpack": s_backpack, "cooler": s_cooler, "gadget": s_gadget,
    "notebook": s_notebook, "pen": s_pen, "koozie": s_koozie, "keychain": s_keychain,
}

_logo_cache = {}


def load_logo(color_name):
    dark = (color_name or "").strip().lower() in DARK
    key = "dark" if dark else "light"
    if key not in _logo_cache:
        fn = "mms_logo_dark.png" if dark else "mms_logo_light.png"
        _logo_cache[key] = Image.open(os.path.join(PRINT_DIR, fn)).convert("RGBA")
    return _logo_cache[key]


def studio_bg(px=W):
    base = Image.new("RGB", (px, px), (236, 240, 244))
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse([px * 0.10, -px * 0.05, px * 0.90, px * 0.82], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(px * 0.13))
    base = Image.composite(Image.new("RGB", (px, px), (253, 254, 255)), base, mask)
    return base.convert("RGBA")


def flatten_file(path):
    """Composite a transparent Printful mockup onto the same studio backdrop as
    the generated items, so the whole grid is cohesive. No-op for opaque images."""
    im = Image.open(path).convert("RGBA")
    if im.getchannel("A").getextrema()[0] == 255:
        return False                      # already opaque (a generated fallback)
    px = max(im.size)
    bg = studio_bg(px)
    bg.alpha_composite(im, ((px - im.width) // 2, (px - im.height) // 2))
    bg.convert("RGB").resize((FINAL, FINAL), Image.LANCZOS).save(path, "PNG")
    return True


def drop_shadow(base, sprite, x, y):
    a = sprite.split()[3].point(lambda p: 95 if p > 8 else 0)
    sh = Image.new("RGBA", sprite.size, (0, 0, 0, 0)); sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(int(W * 0.018)))
    base.alpha_composite(sh, (x + int(W * 0.008), y + int(W * 0.020)))


def compose(item):
    color_name = (item.get("colors") or ["Gray"])[0]
    rgb = COLORS.get(color_name, (150, 158, 167))
    shape = SHAPE.get(item["id"], "gadget")
    sprite = SHAPES[shape](rgb, color_name)
    # scale sprite to ~72% of canvas on its larger axis
    target = int(W * 0.70)
    sc = target / max(sprite.size)
    sprite = sprite.resize((int(sprite.width * sc), int(sprite.height * sc)), Image.LANCZOS)
    base = studio_bg()
    ox = (W - sprite.width) // 2
    oy = (W - sprite.height) // 2
    drop_shadow(base, sprite, ox, oy)
    base.alpha_composite(sprite, (ox, oy))
    # logo
    lw_frac, (fx, fy) = PLACE.get(shape, (0.4, (0.5, 0.5)))
    logo = load_logo(color_name)
    lw = int(sprite.width * lw_frac)
    lh = int(logo.height * (lw / logo.width))
    lg = logo.resize((lw, lh), Image.LANCZOS)
    lx = ox + int(sprite.width * fx) - lw // 2
    ly = oy + int(sprite.height * fy) - lh // 2
    base.alpha_composite(lg, (lx, ly))
    out = base.convert("RGB").resize((FINAL, FINAL), Image.LANCZOS)
    dest = os.path.join(OUT, item["id"] + ".png")
    out.save(dest, "PNG")
    return dest


# ---------------- catalog wiring ----------------
def load_catalog():
    return json.load(open(CATALOG, encoding="utf-8"))


def update_catalog(items):
    for it in items:
        it["image"] = "/asset/products/%s.png" % it["id"]
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
        f.write("\n")
    print("catalog: wrote image field for %d items" % len(items))


# ---------------- builders ----------------
def build_fallbacks(items, only_missing=False):
    n = 0
    for it in items:
        dest = os.path.join(OUT, it["id"] + ".png")
        if only_missing and os.path.exists(dest):
            continue
        compose(it); n += 1
    print("fallbacks: generated %d images -> %s" % (n, OUT))


def build_printful(items, only_ids=None):
    import time
    import config, printful, printful_mockups as pm
    if not config.PRINTFUL_API_KEY:
        print("printful: PRINTFUL_API_KEY not set (.env) — skipping mockups, "
              "generated fallbacks remain.")
        return
    # The mockup-generator endpoints require the store-id header; resolve it once
    # so printful._headers() attaches it to every call.
    sid = config.PRINTFUL_STORE_ID or printful.store_id()
    if sid:
        config.PRINTFUL_STORE_ID = sid
    print("printful: store id = %s" % (sid or "(none)"))
    done = 0
    targets = [it for it in items if it.get("fulfillment") == "printful"
               and (it.get("printful") or {}).get("product_id")
               and (only_ids is None or it["id"] in only_ids)]
    for n, it in enumerate(targets):
        pf = it["printful"]; pid = pf["product_id"]
        # headwear (caps/beanies) are one-size; don't constrain by garment size
        size = None if it.get("category") == "Headwear" else ("L" if it.get("sizes") else "OSFA")
        # prewarm variants via the backoff-aware fetch (avoids empty lists on 429)
        if str(pid) not in printful._variant_cache:
            _st, vd = pm._req("GET", "/products/%s" % pid)
            printful._variant_cache[str(pid)] = ((vd or {}).get("result") or {}).get("variants") or []
        # try the catalog colors in order; fall back to the product's first real
        # variant when the catalog color doesn't exist on this Printful product
        cmap = pf.get("color_map") or {}
        vid, color = None, None
        for col in (it.get("colors") or []):
            v = printful.resolve_variant(pid, cmap.get(col, col), size)
            if v:
                vid, color = v, col; break
        if not vid:
            vs = printful._variant_cache.get(str(pid)) or []
            if vs:
                vid, color = vs[0].get("id"), vs[0].get("color")
                print("  %s: catalog colors not on product %s; using %s" % (it["id"], pid, color))
        if not vid:
            print("  %s: no variant at all — skipped" % it["id"])
            continue
        prefer_chest = it.get("decoration") == "embroidery" and it.get("category") not in ("Headwear",)
        placement = pm.choose_placement(pid, prefer_chest=prefer_chest)
        aw, ah = pm.area_for(pid, vid, placement)
        position = pm.make_position(aw, ah, pm.placement_style(placement))
        logo_url = printful.logo_url_for(color)
        print("  %s: product %s variant %s color %s placement %s area %sx%s ..." %
              (it["id"], pid, vid, color, placement, aw, ah))
        url, info = pm.generate(pid, vid, placement, logo_url, position=position)
        if not url:
            print("  %s: mockup failed (%s)" % (it["id"], info))
            continue
        dest = os.path.join(OUT, it["id"] + ".png")
        pm.download(url, dest)
        flatten_file(dest)
        done += 1
        print("  %s: OK -> %s" % (it["id"], dest))
        if n < len(targets) - 1:
            time.sleep(4)   # pace create-task calls under the rate limit
    print("printful: %d mockups downloaded" % done)


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "all"
    ids = args[1:] or None                       # e.g. `printful ap10` targets one item
    items = load_catalog()
    if cmd in ("all", "fallback"):
        build_fallbacks(items, only_missing=(cmd == "all"))
    if cmd in ("all", "printful"):
        build_printful(items, only_ids=ids)
    if cmd == "flatten":
        n = 0
        for it in items:
            p = os.path.join(OUT, it["id"] + ".png")
            if os.path.exists(p) and flatten_file(p):
                n += 1
        print("flatten: normalized %d mockups" % n)
    if cmd in ("all", "fallback", "catalog"):
        update_catalog(items)
    print("done:", cmd)
