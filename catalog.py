"""Loads the flyer/document catalog from data_catalog.json."""
import json, os
import config

_PATH = os.path.join(config.BASE_DIR, "data_catalog.json")

def load():
    with open(_PATH) as f:
        return json.load(f)

def by_id(cid):
    for d in load():
        if d["id"] == cid:
            return d
    return None
