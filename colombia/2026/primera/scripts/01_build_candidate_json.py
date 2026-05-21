"""
01_build_candidate_json.py — One-time setup: add codcan fields to candidates.json.

**TEMPLATE — BASE_URL MUST BE UPDATED BEFORE ELECTION DAY.**

Fetches the Registraduría primera-vuelta national JSON (municipio code "00"), parses
candidate entries from camaras[].partotabla, and writes the numeric `codcan` field
for each candidate into data/candidates.json.

The `codcan` field is required by the scrapers (02a, 02b) to match API data to the
candidates defined in candidates.json.

Inputs:
  data/candidates.json      ← existing candidate metadata

Output:
  data/candidates.json      ← updated in place with "codcan": <int> per entry

Usage:
  python3 scripts/01_build_candidate_json.py
  python3 scripts/01_build_candidate_json.py --force   # overwrite existing codcan values

⚠️  Before election day:
    1. Confirm the correct BASE_URL from the Registraduría results site.
    2. Confirm the camara index (cam value) for the presidential race.
    3. Run this script once to populate codcan, then run 02a / 02b.
"""

import argparse
import json
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT        = SCRIPT_DIR.parent / "data"
CANDS_JSON = OUT / "candidates.json"

# ⚠️  UPDATE THIS URL BEFORE ELECTION DAY
# Template pattern (replace PR with actual election code if needed):
BASE_URL = "https://resultados1vuelta2026.registraduria.gov.co/json/ACT/PR/{code}.json"

# National-level code for the index JSON (usually "00" or "0000000")
NATIONAL_CODE = "00"

# Camara index for the presidential race (verify on election day)
PRESIDENTIAL_CAM = 0


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Referer":    "https://resultados1vuelta2026.registraduria.gov.co/",
        "User-Agent": "Mozilla/5.0",
        "Accept":     "application/json, */*",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(
        description="Add codcan fields to candidates.json from Registraduría API")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing codcan values (default: skip if already set)")
    args = parser.parse_args()

    print("⚠️  This script is a TEMPLATE.")
    print(f"   BASE_URL = {BASE_URL}")
    print("   Verify the URL and cam index before running on election day.\n")

    with open(CANDS_JSON) as f:
        candidates = json.load(f)

    already_set = all("codcan" in c for c in candidates)
    if already_set and not args.force:
        print("All candidates already have codcan — use --force to overwrite.")
        return

    url = BASE_URL.format(code=NATIONAL_CODE)
    print(f"Fetching: {url}")
    data = fetch_json(url)

    # Find the presidential camara
    pres_cam = None
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) == PRESIDENTIAL_CAM:
            pres_cam = camara
            break

    if pres_cam is None:
        raise RuntimeError(
            f"No camara with cam={PRESIDENTIAL_CAM} found in response. "
            "Check PRESIDENTIAL_CAM constant.")

    # Build codpar → candidate name mapping from API
    api_candidates = []
    for entry in pres_cam.get("partotabla", []):
        p = entry.get("act", entry)
        codpar  = int(p.get("codpar", 0))
        nompar  = str(p.get("nompar", "")).strip()
        api_candidates.append({"codpar": codpar, "nompar": nompar})
        print(f"  API candidate: codpar={codpar:5d}  {nompar}")

    print(f"\nFound {len(api_candidates)} candidates in API response.")
    print("Manual matching required — update CODPAR_MAP in this script with correct values.\n")

    # ── MANUAL MAPPING ────────────────────────────────────────────────────────
    # After running and seeing the API candidates above, fill in this dict:
    #   code (from candidates.json) → codpar (from API)
    # Example (UPDATE THESE VALUES):
    CODPAR_MAP: dict[str, int] = {
        # "cepeda":         1234,
        # "valencia":       5678,
        # "delaespriella":  9012,
        # "claudialopez":   3456,
        # "barreras":       7890,
        # "fajardo":        1111,
        # "caicedo":        2222,
        # "lizcano":        3333,
        # "uribe":          4444,
        # "botero":         5555,
        # "macollins":      6666,
        # "matamoros":      7777,
        # "claralopez":     8888,
    }

    if not CODPAR_MAP:
        print("CODPAR_MAP is empty — fill it in and re-run with --force.")
        return

    # Write codcan into each candidate entry
    updated = 0
    for cand in candidates:
        code = cand["code"]
        if code in CODPAR_MAP:
            cand["codcan"] = CODPAR_MAP[code]
            updated += 1
        elif "codcan" not in cand:
            print(f"  WARNING: no mapping for '{code}'")

    with open(CANDS_JSON, "w") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"Updated {updated}/{len(candidates)} candidates with codcan.")
    print(f"Saved → {CANDS_JSON.name}")


if __name__ == "__main__":
    main()
