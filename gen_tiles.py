"""Generate homepage store-tile thumbnails. Canvas is 2:1 (1000x500) and the
.cap frame uses the same aspect-ratio, so object-fit:cover shows the WHOLE
image with no cropping. All subjects are centered with generous margins."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import card_render

APP = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP, "assets")
TILES = os.path.join(ASSETS, "tiles"); os.makedirs(TILES, exist_ok=True)
THUMBS = os.path.join(APP, "static", "thumbs")
FB = os.path.join(ASSETS, "fonts", "LiberationSans-Bold.ttf")
NAVY=(30,45,59); RED=(200,16,46); GOLD=(237,205,31)
W, H = 1000, 500

def vgrad(size, top, bot):
    w,h=size; g=Image.new("RGB",(1,h))
    for y in range(h):
        t=y/(h-1); g.putpixel((0,y), tuple(int(top[i]+(bot[i]-top[i])*t) for i in range(3)))
    return g.resize((w,h))

def rounded(card, radius=12):
    c = card.convert("RGBA")
    mask = Image.new("L", c.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,c.size[0]-1,c.size[1]-1], radius=radius, fill=255)
    c.putalpha(mask); return c

def paste_center(base, img, cx, cy, angle, scale, shadow=True):
    """Paste img scaled+rotated, centered on (cx,cy)."""
    im = img.convert("RGBA")
    im = im.resize((int(im.width*scale), int(im.height*scale)), Image.LANCZOS)
    im = im.rotate(angle, expand=True, resample=Image.BICUBIC)
    x = int(cx - im.width/2); y = int(cy - im.height/2)
    if shadow:
        a = im.split()[3].point(lambda p: 110 if p>10 else 0)
        sh = Image.new("RGBA", im.size, (0,0,0,0)); sh.putalpha(a)
        sh = sh.filter(ImageFilter.GaussianBlur(9))
        base.alpha_composite(sh, (x+6, y+11))
    base.alpha_composite(im, (x, y))

# ---------- CARDS TILE ----------
def tile_cards():
    base = vgrad((W,H), (247,249,251), (223,229,237)).convert("RGBA")
    emp={"name":"John Doe","title":"Account Manager","email":"jdoe@mmsinconline.com","phone":"555-123-4567"}
    front = rounded(card_render.render_front(emp, scale=2))
    back  = rounded(Image.open(os.path.join(ASSETS,"backs","south.png")).convert("RGB"))
    # back behind (upper-right), front in front (lower-left) - both centered in canvas
    paste_center(base, back,  600, 205, -7, 0.62)
    paste_center(base, front, 430, 295,  6, 0.44)
    base.convert("RGB").save(os.path.join(TILES,"cards.jpg"), "JPEG", quality=90)

# ---------- DOCUMENTS TILE ----------
def tile_docs():
    base = vgrad((W,H), (247,249,251), (221,228,236)).convert("RGBA")
    picks=["doc14.jpg","doc1.jpg","doc16.jpg","doc10.jpg"]
    # centers spread around canvas center (500), fanned
    specs=[(300,255,-12),(430,250,-4),(570,250,5),(700,255,13)]
    for name,(cx,cy,ang) in zip(picks,specs):
        p=os.path.join(THUMBS,name)
        if os.path.exists(p):
            im=Image.open(p).convert("RGB")
            sc=360.0/im.height
            paste_center(base, rounded(im,8), cx, cy, ang, sc)
    base.convert("RGB").save(os.path.join(TILES,"documents.jpg"), "JPEG", quality=90)

# ---------- SWAG TILE ----------
def polo(w,h,color,accent):
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    bx=int(w*0.16)
    d.rounded_rectangle([bx,int(h*0.22),w-bx,h-2], radius=int(w*0.08), fill=color)
    d.polygon([(bx,int(h*0.24)),(2,int(h*0.5)),(bx,int(h*0.6))], fill=color)
    d.polygon([(w-bx,int(h*0.24)),(w-2,int(h*0.5)),(w-bx,int(h*0.6))], fill=color)
    cx=w//2
    d.polygon([(cx-int(w*0.14),int(h*0.2)),(cx,int(h*0.42)),(cx+int(w*0.14),int(h*0.2)),(cx,int(h*0.14))], fill=color)
    d.polygon([(cx-int(w*0.09),int(h*0.2)),(cx,int(h*0.36)),(cx+int(w*0.09),int(h*0.2))], fill=(255,255,255))
    d.line([(cx,int(h*0.36)),(cx,int(h*0.52))], fill=(255,255,255), width=3)
    for i in range(2): d.ellipse([cx-3,int(h*0.4)+i*14,cx+3,int(h*0.4)+i*14+6], fill=(255,255,255))
    d.ellipse([int(w*0.60),int(h*0.42),int(w*0.60)+18,int(h*0.42)+18], outline=accent, width=4)
    return im

def tumbler(w,h):
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle([int(w*0.2),2,int(w*0.8),h-2], radius=int(w*0.18), fill=(214,220,226))
    d.rounded_rectangle([int(w*0.2),2,int(w*0.44),h-2], radius=int(w*0.18), fill=(232,236,240))
    d.rounded_rectangle([int(w*0.2),2,int(w*0.8),int(h*0.16)], radius=int(w*0.1), fill=(60,72,84))
    d.rectangle([int(w*0.34),int(h*0.42),int(w*0.66),int(h*0.5)], fill=RED)
    return im

def cap(w,h):
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.pieslice([2,2,w-2,int(h*1.7)], 180, 360, fill=NAVY)
    d.ellipse([int(w*0.05),int(h*0.55),w-2,int(h*0.95)], fill=(24,36,48))
    d.ellipse([int(w*0.44),int(h*0.3),int(w*0.56),int(h*0.42)], fill=RED)
    return im

def tile_swag():
    base = vgrad((W,H), (36,54,70), (18,28,38)).convert("RGBA")
    d=ImageDraw.Draw(base)
    glow=Image.new("RGBA",(W,H),(0,0,0,0)); ImageDraw.Draw(glow).ellipse([W-430,-140,W+140,300], fill=(200,16,46,60))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)))
    d.text((70,175), "MMS", font=ImageFont.truetype(FB,84), fill=(255,255,255))
    d.text((74,285), "BRANDED APPAREL & SWAG", font=ImageFont.truetype(FB,24), fill=GOLD)
    paste_center(base, polo(320,320,NAVY,RED), 620, 250, -4, 1.0)
    paste_center(base, tumbler(130,250), 800, 235, 4, 1.0)
    paste_center(base, cap(200,130), 815, 360, -6, 1.0)
    base.convert("RGB").save(os.path.join(TILES,"swag.jpg"), "JPEG", quality=90)

tile_cards(); tile_docs(); tile_swag()
print("tiles:", sorted(os.listdir(TILES)))
for t in ["cards.jpg","documents.jpg","swag.jpg"]:
    print(t, Image.open(os.path.join(TILES,t)).size)
