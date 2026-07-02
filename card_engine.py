"""
Card generation engine — builds a print-ready, 2-sided business card PDF
(3.5 x 2 in + 4mm bleed) that is 1:1 with the official MMS template:
  page 1 = personalized FRONT composited on the official blank front
  page 2 = the official line-card BACK, auto-selected by role/territory.
"""
import os
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import config, card_render

ASSETS = config.ASSET_DIR
BACKS = {
    "both":  os.path.join(ASSETS, "backs", "both.png"),   # combined line cards
    "north": os.path.join(ASSETS, "backs", "north.png"),  # MN/WI/Dakotas
    "south": os.path.join(ASSETS, "backs", "south.png"),  # IA/NE/Western IL
}

TRIM_W, TRIM_H = 3.5 * inch, 2.0 * inch
BLEED = 4 * mm
PAGE_W, PAGE_H = TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED

def pick_back(emp):
    if emp.get("role", "").lower() == "technician":
        return BACKS["both"]
    return BACKS["north"] if emp.get("territory", "").lower() == "north" else BACKS["south"]

def generate_card_pdf(emp, out_path):
    """emp = {name,title,email,phone,role,territory}. Returns out_path (2-page PDF)."""
    c = canvas.Canvas(out_path, pagesize=(PAGE_W, PAGE_H))
    # FRONT — composite personalized text + QR onto the official blank front
    front = card_render.render_front(emp, scale=4)
    c.drawImage(ImageReader(front), 0, 0, width=PAGE_W, height=PAGE_H, preserveAspectRatio=False)
    c.showPage()
    # BACK — official line-card art
    c.drawImage(pick_back(emp), 0, 0, width=PAGE_W, height=PAGE_H, mask="auto", preserveAspectRatio=False)
    c.showPage()
    c.save()
    return out_path
