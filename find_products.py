"""
Helper: list the exact Gelato product UIDs for business cards and flyers
so you can paste the right ones into .env. Needs GELATO_API_KEY set.

Usage:  GELATO_API_KEY=xxxx python find_products.py
"""
import json, config, gelato

def show(catalog, filters):
    print(f"\n=== catalog: {catalog} (filters={filters}) ===")
    status, data = gelato.search_products(catalog, filters, limit=40)
    if status not in (200, 0):
        print("  error:", status, data); return
    for p in (data.get("products") or [])[:40]:
        a = p.get("attributes", {})
        dim = p.get("dimensions", {})
        size = ""
        if "Width" in dim and "Height" in dim:
            size = f'{dim["Width"]["value"]}x{dim["Height"]["value"]}{dim["Width"]["measureUnit"]}'
        print(f'  {p["productUid"]}   [{a.get("PaperFormat","")} {a.get("ColorType","")} {size}]')

if __name__ == "__main__":
    if not config.GELATO_API_KEY:
        print("Set GELATO_API_KEY first (see .env.example)."); raise SystemExit(1)
    # Business cards (4-4 = double sided color). Adjust filters as needed.
    show("cards",  {"ColorType": ["4-4"]})
    # Flyers (single/letter). Catalog may be 'flyers'.
    show("flyers", {"ColorType": ["4-4", "4-0"]})
    print("\nPick the UID that matches your stock/size and put it in .env as CARD_PRODUCT_UID / FLYER_PRODUCT_UID.")
