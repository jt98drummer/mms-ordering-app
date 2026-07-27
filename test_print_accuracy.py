"""Guard: the Printful ORDER must print exactly what the storefront PREVIEW showed.

    MAIL_MODE=off PRINTFUL_MODE=dry python test_print_accuracy.py

The storefront mockups were rendered with a specific placement + position; those
values are frozen into swag_catalog.json (`gen_products.py printspec`). This
test builds the real order payload via _fulfill_swag() and asserts it carries
that exact placement + position — plus a colour-appropriate logo and matching
embroidery threads. Runs offline (dry mode); no API calls, no orders created.

Regression this prevents: fulfillment used to send {"type":"default"} with no
position, so Printful auto-fitted the logo to the whole print area — a 12" tee
print where the preview showed 7.7".
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PRINTFUL_MODE", "dry")
os.environ.setdefault("MAIL_MODE", "off")

import config, printful, branding, app                      # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (("  " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


CAT = {i["id"]: i for i in json.load(open(os.path.join(config.BASE_DIR, "swag_catalog.json"),
                                          encoding="utf-8"))}

captured = []
printful.create_order = lambda items, r: (captured.extend(items), (0, {"mode": "dry"}))[1]
# Run fully offline: variant resolution is validated separately (all catalog
# colour/size combos resolve against the live Printful catalog). Here we only
# assert how the print file is placed on whatever variant is chosen.
config.PRINTFUL_ENABLED = True
printful.resolve_variant = lambda pid, color, size: 999999

SHIP = {"firstName": "A", "lastName": "B", "addressLine1": "1 Main", "city": "DSM",
        "state": "IA", "postCode": "50266", "country": "US", "email": "e@x", "phone": "5"}

print("\n=== Printful order payload vs storefront preview spec ===")
for iid, item in sorted(CAT.items()):
    if item.get("fulfillment") != "printful" or not item.get("published"):
        continue
    pf = item["printful"]
    for color in item["colors"]:
        for logo in branding.item_logo_options(item, color):
            captured.clear()
            size = item["sizes"][len(item["sizes"]) // 2] if item.get("sizes") else ""
            app._fulfill_swag({
                "oid": "T", "orderer": "x", "orderer_email": "x@y", "purpose": "p",
                "_ship": SHIP,
                "items": [{"type": "swag", "id": iid, "name": item["name"], "color": color,
                           "size": size, "qty": 1, "logo": logo}],
            })
            tag = "%s/%s/%s" % (iid, color, logo)
            if not captured:
                check(tag + " produced an order line", False)
                continue
            f = captured[0]["files"][0]
            check(tag + " placement matches preview",
                  f.get("type") == pf.get("print_placement"),
                  "%r != %r" % (f.get("type"), pf.get("print_placement")))
            check(tag + " position matches preview",
                  f.get("position") == pf.get("print_position"),
                  "%r != %r" % (f.get("position"), pf.get("print_position")))
            check(tag + " logo file is the chosen variant",
                  f.get("url", "").endswith(branding.LOGOS[logo]["file"]))
            check(tag + " logo contrasts the garment",
                  branding.logo_contrast(color, logo, branding.item_hex(item, color))
                  >= branding.MIN_CONTRAST)
            if item.get("decoration") == "embroidery":
                opts = {o["id"]: o["value"] for o in captured[0].get("options", [])}
                want_id = pf.get("thread_option") or "thread_colors"
                # the option id is placement-specific; a wrong id is a hard 400
                check(tag + " uses the product's thread option id",
                      want_id in opts, "%r not in %r" % (want_id, list(opts)))
                # values must be from Printful's fixed palette (brand red is not)
                check(tag + " thread colours are orderable + match the logo",
                      opts.get(want_id) == branding.printful_threads(logo),
                      "%r != %r" % (opts.get(want_id), branding.printful_threads(logo)))
                check(tag + " no unorderable thread hex sent",
                      all(v in branding.PRINTFUL_THREADS for v in (opts.get(want_id) or [])))

print("\n" + ("ALL PRINT-ACCURACY CHECKS PASSED" if not FAILS else "FAILURES: %d" % len(FAILS)))
sys.exit(1 if FAILS else 0)
