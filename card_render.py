"""
Renders the business-card FRONT by compositing personalized text + vCard QR
onto the official blank front template (assets/front_blank.png). This guarantees
the preview and the print file are 1:1 with the official MMS template.
Reference template grid is 513 x 292 px; all field coordinates are in that grid.
"""
import os, io, qrcode
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
BLANK = os.path.join(ASSETS, "front_blank.png")
FONT_BOLD = os.path.join(ASSETS, "fonts", "LiberationSans-Bold.ttf")

RED = (200, 16, 46)
BLACK = (17, 17, 17)

# field = (x, baseline_y, font_px, color) in the 513x292 template grid
FIELDS = {
    "name":  (13, 151, 25, RED),
    "title": (13, 178, 15, BLACK),
    "email": (13, 212, 14, BLACK),
    "phone": (14, 237, 14, BLACK),
}
QR_X, QR_Y, QR_SIZE = 322, 111, 143
COMPANY_URL = "www.mmsinconline.com"

def _vcard_qr(emp, px):
    first, last = (emp.get("name", "").split(" ", 1) + [""])[:2]
    vcard = ("BEGIN:VCARD\nVERSION:3.0\n"
             f"N:{last};{first}\nFN:{emp.get('name','')}\n"
             "ORG:Miller Mechanical Specialties Inc.\n"
             f"TITLE:{emp.get('title','')}\n"
             f"EMAIL;TYPE=WORK:{emp.get('email','')}\n"
             f"TEL;TYPE=WORK,VOICE:{emp.get('phone','')}\n"
             f"URL:https://{COMPANY_URL}\nEND:VCARD\n")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0)
    qr.add_data(vcard); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((px, px), Image.NEAREST)

def render_front(emp, scale=4):
    """Return a PIL RGB image of the personalized front at (513*scale)x(292*scale)."""
    base = Image.open(BLANK).convert("RGB")
    W, H = base.size
    img = base.resize((W * scale, H * scale), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for key in ("name", "title", "email", "phone"):
        x, by, sz, col = FIELDS[key]
        text = emp.get(key, "") or ""
        if not text:
            continue
        font = ImageFont.truetype(FONT_BOLD, sz * scale)
        d.text((x * scale, by * scale), text, font=font, fill=col, anchor="ls")
    qr = _vcard_qr(emp, QR_SIZE * scale)
    img.paste(qr, (QR_X * scale, QR_Y * scale))
    return img

def front_png_bytes(emp, scale=3):
    img = render_front(emp, scale=scale)
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return buf.getvalue()
