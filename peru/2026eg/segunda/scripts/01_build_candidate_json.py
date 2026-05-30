"""
01_build_candidate_json.py — Peru 2026 EG Segunda Vuelta

Adds the ONPE `codigoAgrupacionPolitica` field to each candidate in
data/candidates.json. This numeric code is the key used by the 02a/02b
scrapers to match API results to candidates.

The code is fetched from:
  GET /presentacion-backend/eleccion-presidencial/participantes-ubicacion-geografica-nombre
       ?idEleccion=10&tipoFiltro=eleccion

Inputs:
  data/candidates.json          ← candidate metadata (nombre, partido, color)

Output:
  data/candidates.json          ← updated in place with "codcan": <int> per entry

Usage:
  python3 scripts/01_build_candidate_json.py
  python3 scripts/01_build_candidate_json.py --force   # overwrite existing values
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("curl_cffi not installed. Run: pip install curl_cffi")

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
CANDS_JSON = DATA_DIR / "candidates.json"

BASE_URL    = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend"
ID_ELECCION = 11  # TODO: confirm segunda vuelta election ID from ONPE before election day

_session = cffi_requests.Session(impersonate="chrome124")
_session.headers.update({
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Referer":         "https://resultadoelectoral.onpe.gob.pe/main/presidenciales",
    "Origin":          "https://resultadoelectoral.onpe.gob.pe",
})


def fetch_json(url: str) -> dict:
    r = _session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_candidates() -> list[dict]:
    """Fetch national candidate list from ONPE API."""
    url = (
        f"{BASE_URL}/eleccion-presidencial/participantes-ubicacion-geografica-nombre"
        f"?idEleccion={ID_ELECCION}&tipoFiltro=eleccion"
    )
    print(f"Fetching: {url}")
    data = fetch_json(url)
    if not data.get("success"):
        raise RuntimeError(f"API error: {data.get('message')}")
    return data.get("data", [])


def main():
    parser = argparse.ArgumentParser(
        description="Add ONPE codigoAgrupacionPolitica to candidates.json")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing codcan values")
    args = parser.parse_args()

    with open(CANDS_JSON) as f:
        candidates = json.load(f)

    already_set = all("codcan" in c for c in candidates)
    if already_set and not args.force:
        print("All candidates already have codcan — use --force to overwrite.")
        return

    api_cands = fetch_candidates()

    # Build lookup: nombre → codigoAgrupacionPolitica
    # Exclude blank/null vote entries (code 80, 81)
    api_map = {}
    for c in api_cands:
        code = int(c.get("codigoAgrupacionPolitica", 0))
        if code in (80, 81):
            continue
        nombre = str(c.get("nombreCandidato", "")).strip()
        api_map[nombre] = code
        print(f"  API: {code:3d}  {nombre}")

    print(f"\nFound {len(api_map)} candidates in API response.\n")

    # Match candidates.json by nombre
    updated, unmatched = 0, []
    for cand in candidates:
        nombre = cand.get("nombre", "").strip()
        if nombre in api_map:
            if "codcan" not in cand or args.force:
                cand["codcan"] = api_map[nombre]
                updated += 1
        else:
            # Try partial match (candidate name may have accents/spacing differences)
            matches = [k for k in api_map if nombre in k or k in nombre]
            if matches:
                cand["codcan"] = api_map[matches[0]]
                updated += 1
                print(f"  Fuzzy match: '{nombre}' → '{matches[0]}' (code {cand['codcan']})")
            else:
                unmatched.append(nombre)

    if unmatched:
        print(f"\nWARN: No API match for {len(unmatched)} candidates:")
        for n in unmatched:
            print(f"  - {n}")

    with open(CANDS_JSON, "w") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"\nUpdated {updated}/{len(candidates)} candidates with codcan.")
    print(f"Saved → {CANDS_JSON.name}")


if __name__ == "__main__":
    main()
