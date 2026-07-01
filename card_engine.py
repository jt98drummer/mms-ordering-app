"""
Card generation engine.
Produces a print-ready, two-sided business card PDF (3.5 x 2 in + 4mm bleed):
  page 1 = personalized front (name/title/email/phone + scannable vCard QR)
  page 2 = the correct line-card back, auto-selected by role/territory.
Gelato receives this single 2-page PDF as the 'default' print file.
"""
import os, io, qrcode
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import Color, black, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import config

ASSETS = config.ASSET_DIR
LOGO   = os.path.join(ASSETS, "mms_logo.png")
BACKS  = {
    "both":  os.path.join(ASSETS, "backs", "both.png"),
    "north": os.path.join(ASSETS, "backs", "north.png"),   # MN/WI/Dakotas
    "south": os.path.join(ASSETS, "backs", "south.png"),   # IA/NE/Western IL
}
MMS_RED = Color(200/255, 16/255, 46/255)   # official #C8102E

TRIM_W, TRIM_H = 3.5*inch, 2.0*inch
BLEED = 4*mm
PAGE_W, PAGE_H = TRIM_W + 2*BLEED, TRIM_H + 2*BLEED
REF_W, REF_H = 513.0, 292.0

def fx(px): return BLEED + (px/REF_W)*TRIM_W
def fy(py): return BLEED + (1 - py/REF_H)*TRIM_H

def _qr(emp):
    first, last = (emp["name"].split(" ", 1) + [""])[:2]
    vcard = ("BEGIN:VCARD\nVERSION:3.0\n"
             f"N:{last};{first}\nFN:{emp['name']}\n"
             f"ORG:{config.COMPANY_NAME}\nTITLE:{emp['title']}\n"
             f"EMAIL;TYPE=WORK:{emp['email']}\nTEL;TYPE=WORK,VOICE:{emp['phone']}\n"
             f"URL:https://{config.COMPANY_URL}\nEND:VCARD\n")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0)
    qr.add_data(vcard); qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return ImageReader(buf)

def pick_back(emp):
    if emp.get("role", "").lower() == "technician":
        return BACKS["both"]
    return BACKS["north"] if emp.get("territory", "").lower() == "north" else BACKS["south"]

def _front(c, emp):
    c.setFillColor(white); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(MMS_RED); c.rect(0, fy(75), PAGE_W, fy(49)-fy(75), fill=1, stroke=0)
    c.drawImage(LOGO, fx(19), fy(109), width=fx(301)-fx(19), height=fy(11)-fy(109), mask='auto', preserveAspectRatio=False)
    c.setFillColor(MMS_RED); c.setFont("Helvetica-Bold", 15); c.drawString(fx(14), fy(150), emp["name"])
    c.setFillColor(black); c.setFont("Helvetica-Bold", 9.5); c.drawString(fx(14), fy(174), emp["title"])
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(fx(14), fy(212), emp["email"])
    c.drawString(fx(14), fy(232), emp["phone"])
    c.drawString(fx(14), fy(278), config.COMPANY_URL)
    qr = _qr(emp); size = fx(470)-fx(325)
    c.drawImage(qr, fx(325), fy(112)-size, width=size, height=size, mask='auto')
    c.setFont("Helvetica-Bold", 9); c.drawCentredString(fx(325)+size/2, fy(280), "Add as Contact")

def _back(c, emp):
    c.setFillColor(white); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.drawImage(pick_back(emp), 0, 0, width=PAGE_W, height=PAGE_H, mask='auto', preserveAspectRatio=False)

def generate_card_pdf(emp, out_path):
    """emp = {name,title,email,phone,role,territory}. Returns out_path (2-page PDF)."""
    c = canvas.Canvas(out_path, pagesize=(PAGE_W, PAGE_H))
    _front(c, emp); c.showPage()
    _back(c, emp);  c.showPage()
    c.save()
    return out_path
