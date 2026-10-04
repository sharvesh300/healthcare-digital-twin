"""Build the medication reference seeds from RxNorm (NLM RxNav API).

Inputs
  * RxNorm product codes found in the Synthea bundles (data/synthea/fhir)
  * ingredient names listed in seeds/mappings/medication_names.csv (other sources)

Outputs (committed, reviewable)
  seeds/reference/medication.csv          medication_id (= RxNorm ingredient RxCUI), name
  seeds/reference/medication_atc.csv      medication_id, atc4 (ATC level-4 classes from RxClass)
  seeds/reference/medication_product.csv  product_rxcui, medication_id, display, strength_value, strength_unit
  seeds/mappings/medication_names.csv     source name -> medication_id (resolved column filled in)

API responses are cached in data/cache/rxnav.json, so reruns are offline and fast.

    uv run python seeds/build_medication_seeds.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RXNAV = "https://rxnav.nlm.nih.gov/REST"
CACHE = ROOT / "data" / "cache" / "rxnav.json"
SYNTHEA = ROOT / "data" / "synthea" / "fhir"
NAMES = ROOT / "seeds" / "mappings" / "medication_names.csv"
OUT = ROOT / "seeds" / "reference"
STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(MG|UNT|MCG|MEQ|G)(?:/(ML|ACTUAT|HR))?\b", re.I)

_cache: dict[str, dict] = json.loads(CACHE.read_text()) if CACHE.exists() else {}


def get(path: str) -> dict:
    if path not in _cache:
        for attempt in range(5):
            try:
                with urllib.request.urlopen(f"{RXNAV}/{path}", timeout=60) as r:
                    _cache[path] = json.load(r)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache))
    return _cache[path]


def concepts(payload: dict) -> list[dict]:
    groups = payload.get("relatedGroup", {}).get("conceptGroup", []) or []
    return [c for g in groups for c in g.get("conceptProperties", []) or []]


def ingredients_of(product_rxcui: str) -> list[dict]:
    """[{rxcui, name, strength_value, strength_unit}] for a product (one per ingredient)."""
    ins = concepts(get(f"rxcui/{product_rxcui}/related.json?tty=IN"))
    if not ins:  # the code is itself an ingredient (or a precise ingredient)
        props = get(f"rxcui/{product_rxcui}/properties.json").get("properties") or {}
        if props.get("tty") in ("IN", "PIN", "MIN"):
            return [{"rxcui": props["rxcui"], "name": props["name"].lower(), "strength_value": None, "strength_unit": None}]
        return []
    components = [c["name"] for c in concepts(get(f"rxcui/{product_rxcui}/related.json?tty=SCDC"))]
    out = []
    for ing in ins:
        strength = next((s for s in components if ing["name"].lower() in s.lower()), None)
        m = STRENGTH.search(strength or "")
        out.append({
            "rxcui": ing["rxcui"], "name": ing["name"].lower(),
            "strength_value": m.group(1) if m else None,
            "strength_unit": (m.group(2).lower() + (f"/{m.group(3).lower()}" if m.group(3) else "")) if m else None,
        })
    return out


def atc4_of(ingredient_rxcui: str) -> list[str]:
    """ATC-4 classes of the ingredient itself. RxClass also returns the classes of every
    combination product containing it (tty MIN, e.g. simvastatin -> A10BH via
    sitagliptin/simvastatin); those are dropped unless nothing else is known."""
    info = get(f"rxclass/class/byRxcui.json?rxcui={ingredient_rxcui}&relaSource=ATC")
    items = (info.get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo", [])
    own = {i["rxclassMinConceptItem"]["classId"] for i in items if i["minConcept"].get("tty") in ("IN", "PIN")}
    return sorted(own or {i["rxclassMinConceptItem"]["classId"] for i in items})


def rxcui_for_name(name: str) -> str | None:
    """Exact/normalised RxNorm match first, then RxNav's approximate match (top candidate)."""
    ids = (get(f"rxcui.json?name={urllib.parse.quote(name)}&search=2").get("idGroup") or {}).get("rxnormId")
    if ids:
        return ids[0]
    approx = get(f"approximateTerm.json?term={urllib.parse.quote(name)}&maxEntries=1")
    candidates = (approx.get("approximateGroup") or {}).get("candidate") or []
    return candidates[0]["rxcui"] if candidates else None


def not_a_drug(name: str) -> bool:
    return name.strip().isdigit() or "unspecified" in name.lower()


def synthea_products() -> dict[str, str]:
    products: dict[str, str] = {}
    for path in sorted(SYNTHEA.glob("*.json")):
        if path.name.startswith(("hospital", "practitioner")):
            continue
        for e in json.loads(path.read_bytes())["entry"]:
            r = e["resource"]
            concept = r.get("medicationCodeableConcept") if r["resourceType"] == "MedicationRequest" else (
                r.get("code") if r["resourceType"] == "Medication" else None)
            for c in (concept or {}).get("coding", []):
                if c.get("system", "").endswith("rxnorm"):
                    products[c["code"]] = c.get("display", "")
    return products


def main() -> None:
    meds: dict[str, str] = {}
    product_rows = []
    products = synthea_products()
    print(f"{len(products)} Synthea product codes")
    for i, (code, display) in enumerate(sorted(products.items()), 1):
        for ing in ingredients_of(code):
            meds[ing["rxcui"]] = ing["name"]
            product_rows.append({"product_rxcui": code, "medication_id": ing["rxcui"], "display": display,
                                 "strength_value": ing["strength_value"] or "", "strength_unit": ing["strength_unit"] or ""})
        if i % 20 == 0:
            print(f"  products {i}/{len(products)}", flush=True)

    name_rows = []
    if NAMES.exists():
        with NAMES.open(newline="") as fh:
            name_rows = list(csv.DictReader(fh))
        for k, row in enumerate(name_rows, 1):
            if k % 50 == 0:
                print(f"  names {k}/{len(name_rows)}", flush=True)
            # Source codes for refused/unknown (e.g. NHANES 77777, 99999) and unspecified drug
            # categories are not drugs; approximate matching would map them to nonsense.
            if not_a_drug(row["source_name"]):
                row["medication_id"] = ""
                continue
            rxcui = rxcui_for_name(row["ingredient"])
            if rxcui:
                ings = ingredients_of(rxcui) or [{"rxcui": rxcui, "name": row["ingredient"].lower()}]
                row["medication_id"] = ings[0]["rxcui"]
                meds.setdefault(ings[0]["rxcui"], ings[0]["name"])
            else:
                row["medication_id"] = ""
                print(f"  unresolved name: {row['ingredient']}", file=sys.stderr)

    atc_rows = []
    for j, rxcui in enumerate(sorted(meds, key=int), 1):
        atc_rows += [{"medication_id": rxcui, "atc4": a} for a in atc4_of(rxcui)]
        if j % 20 == 0:
            print(f"  ATC {j}/{len(meds)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "medication.csv", ["medication_id", "name"],
          [{"medication_id": k, "name": v} for k, v in sorted(meds.items(), key=lambda kv: int(kv[0]))])
    write(OUT / "medication_atc.csv", ["medication_id", "atc4"], atc_rows)
    write(OUT / "medication_product.csv", ["product_rxcui", "medication_id", "display", "strength_value", "strength_unit"],
          sorted(product_rows, key=lambda r: (int(r["product_rxcui"]), int(r["medication_id"]))))
    if name_rows:
        write(NAMES, list(name_rows[0].keys()), name_rows)
    print(f"{len(meds)} ingredients, {len(atc_rows)} ATC links, {len(product_rows)} product links")


def write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
