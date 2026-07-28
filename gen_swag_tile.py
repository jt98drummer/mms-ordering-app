"""Build the homepage Swag tile from REAL store product mockups (not drawings).

    python gen_swag_tile.py        -> assets/tiles/swag.jpg

Picks a few hero images out of assets/products/, cuts them out of their studio
backdrop and arranges them over the MMS navy gradient. Re-run after adding or
re-rendering products so the tile always reflects what's actually in the store.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

APP = os.path.dirname(os.path.abspath(__file__))
PROD = os.path.join(APP, "assets", "products")
TILES = os.path.join(APP, "assets", "tiles"); os.makedirs(TILES, exist_ok=True)
FB = os.path.join(APP, "assets", "fonts", "LiberationSans-Bold.ttf")
NAVY, GOLD = (30, 45, 59), (237, 205, 31)
W, H = 1000, 500                      # 2:1, matches the .cap frame


def vgrad(size, top, bot):
    w, h = size; g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return g.resize((w, h))


def script_logo():
    """The official MMS script WITHOUT the tagline, in white (for the navy tile).

    Crops assets/print/mms_white.png above the blank band that separates the
    script from the 'MILLER MECHANICAL SPECIALTIES' wordmark, so we use the real
    brand asset rather than typing 'MMS' in a font."""
    im = Image.open(os.path.join(APP, "assets", "print", "mms_white.png")).convert("RGBA")
    a = im.split()[3]; w, h = im.size; px = a.load()
    rows = []
    for y in range(h):
        rows.append(any(px[x, y] > 40 for x in range(0, w, 4)))
    gap_start, best, cur = None, None, None      # widest blank band in the lower half
    for y in range(h):
        if not rows[y]:
            cur = y if cur is None else cur
        elif cur is not None:
            if cur > h * 0.4 and (best is None or (y - cur) > best[1] - best[0]):
                best = (cur, y)
            cur = None
    cut = best[0] if best else h
    out = im.crop((0, 0, w, cut))
    return out.crop(out.split()[3].getbbox())


def cutout(path, light=222, small=512):
    """Lift the product off its studio backdrop -> RGBA, tight-cropped.

    Flood-fills the LIGHT region inward from the borders, so the backdrop (which
    is a soft gradient, not one flat colour) is removed wherever it touches an
    edge, while light pixels INSIDE the product — the white MMS logo — are kept
    because they aren't connected to the border. Mask is computed small and
    upscaled, which is plenty for a 1000x500 tile and keeps it fast.
    """
    im = Image.open(path).convert("RGB")
    thumb = im.resize((small, small), Image.LANCZOS).convert("L")
    tp = thumb.load()
    bgmask = [[False] * small for _ in range(small)]
    stack = []
    for i in range(small):                      # seed every light border pixel
        for (x, y) in ((i, 0), (i, small - 1), (0, i), (small - 1, i)):
            if tp[x, y] >= light and not bgmask[y][x]:
                bgmask[y][x] = True; stack.append((x, y))
    while stack:                                # 4-way flood fill
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < small and 0 <= ny < small and not bgmask[ny][nx] and tp[nx, ny] >= light:
                bgmask[ny][nx] = True; stack.append((nx, ny))
    # Enclosed light regions (e.g. the gap under a tote handle) are NOT reachable
    # from the border, so clear any that are large. Small enclosed light areas are
    # kept — those are the white logo strokes.
    hole_min = int(small * small * 0.010)
    for sy in range(small):
        for sx in range(small):
            if bgmask[sy][sx] or tp[sx, sy] < light:
                continue
            comp, st = [], [(sx, sy)]
            bgmask[sy][sx] = True
            while st:
                x, y = st.pop(); comp.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < small and 0 <= ny < small and not bgmask[ny][nx] and tp[nx, ny] >= light:
                        bgmask[ny][nx] = True; st.append((nx, ny))
            if len(comp) < hole_min:                  # keep it (logo) -> unmark
                for (x, y) in comp:
                    bgmask[y][x] = False

    m = Image.new("L", (small, small), 255); mp = m.load()
    for y in range(small):
        row = bgmask[y]
        for x in range(small):
            if row[x]:
                mp[x, y] = 0
    m = m.resize(im.size, Image.LANCZOS)
    # Pull the matte IN a couple of pixels then feather it. Without this the
    # upscaled mask keeps a light rim of studio backdrop, which reads as a
    # jagged white outline once the product sits on the dark tile.
    m = m.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.6))
    m = m.point(lambda p: 0 if p < 90 else min(255, int((p - 90) * 255 / 130)))
    out = im.convert("RGBA"); out.putalpha(m)
    bbox = m.point(lambda p: 255 if p > 40 else 0).getbbox()
    return out.crop(bbox) if bbox else out


def place(base, img, cx, cy, target_h, angle=0):
    sc = target_h / img.height
    im = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.LANCZOS)
    if angle:
        im = im.rotate(angle, expand=True, resample=Image.BICUBIC)
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    a = im.split()[3].point(lambda p: 120 if p > 8 else 0)
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(11))
    base.alpha_composite(sh, (x + 7, y + 13))
    base.alpha_composite(im, (x, y))


def build():
    base = vgrad((W, H), (36, 54, 70), (18, 28, 38)).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W - 470, -150, W + 150, 320], fill=(200, 16, 46, 70))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(75)))

    # Real MMS script logo (no tagline), not typed text
    lg = script_logo()
    lw = 300
    lg = lg.resize((lw, max(1, int(lg.height * lw / lg.width))), Image.LANCZOS)
    base.alpha_composite(lg, (66, 150))

    d = ImageDraw.Draw(base)
    # Auto-fit the strapline to the left column so it can never run under the
    # product cluster (the products start around x=430).
    label, maxw = "BRANDED APPAREL & SWAG", 408
    size = 34
    while size > 16:
        fnt = ImageFont.truetype(FB, size)
        if d.textlength(label, font=fnt) <= maxw:
            break
        size -= 1
    d.text((70, 150 + lg.height + 22), label, font=fnt, fill=GOLD)

    # (file, centre x, centre y, height, rotation) - real store mockups
    layout = [("ap3.png", 566, 258, 340, -3),    # tee
              ("ap10.png", 768, 162, 152, 4),    # cap
              ("ev4.png", 800, 336, 252, 0),     # insulated tumbler
              ("ev7.png", 912, 232, 208, 4)]     # hardcover journal
    for fn, cx, cy, th, ang in layout:
        p = os.path.join(PROD, fn)
        if os.path.exists(p):
            place(base, cutout(p), cx, cy, th, ang)
        else:
            print("  skip (missing):", fn)
    dest = os.path.join(TILES, "swag.jpg")
    base.convert("RGB").save(dest, "JPEG", quality=92)
    print("wrote", dest, base.size)


if __name__ == "__main__":
    build()
