"""
02_build_party_jsons.py  —  ONE-TIME initializer for party JSON files.

Hits the Registraduría national summary endpoint (00.json) to get all party
codes + names, then writes:
  data/national_parties.json   (cam=0, nacional)
  data/indigena_parties.json   (cam=4, indígena)

Existing files are NOT overwritten unless --force is passed.
After running, manually set "color" for each party; subsequent scrapes via
01_scrape_municipios.py will only update "votes" and never touch nombre/color.

Usage:
  python3 02_build_party_jsons.py           # skip if files exist
  python3 02_build_party_jsons.py --force   # regenerate (preserves colors)
"""

import argparse
import json
import ssl
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

SUMMARY_URL = "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/SE/00.json"
HEADERS = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def fetch_summary() -> dict:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(SUMMARY_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read())


def build_party_list(data: dict, cam_id: int, prefix: str) -> list[dict]:
    """
    Extract parties from the given camara.  Returns list sorted by votes desc.
    Party name comes from 'nompar' field in each partotabla entry.
    """
    for camara in data.get("camaras", []):
        if int(camara.get("cam", -1)) != cam_id:
            continue
        parties = {}
        for pw in camara.get("partotabla", []):
            p    = pw.get("act", pw)
            cod  = str(int(p.get("codpar", 0))).zfill(4)
            nom  = (p.get("nompar") or p.get("nombre") or cod).strip()
            vot  = int(p.get("vot") or 0)
            if cod not in parties:
                parties[cod] = {"code": cod, "nombre": nom, "display_name": "", "color": "#888"}
            parties[cod]["votes"] += vot
        return sorted(parties.values(), key=lambda x: -x["votes"])
    return []


def merge_preserve_colors(existing_path: Path, new_parties: list[dict]) -> list[dict]:
    """
    If the file already exists, keep existing nombre/color/display_name for matching codes.
    Adds new codes not yet in the file.  Never removes existing entries.
    Party JSONs are metadata-only (code, nombre, display_name, color) — no votes.
    """
    if not existing_path.exists():
        return new_parties
    with open(existing_path) as f:
        existing = {str(p["code"]).zfill(4): p for p in json.load(f)}
    merged = dict(existing)
    for p in new_parties:
        code = str(p["code"]).zfill(4)
        if code not in merged:
            merged[code] = p                      # new party, default color
    # Preserve existing order (alphabetical / by code); new ones appended
    return list(merged.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files already exist (colors preserved)")
    args = parser.parse_args()

    nat_path = OUT / "national_parties.json"
    ind_path = OUT / "indigena_parties.json"

    if nat_path.exists() and ind_path.exists() and not args.force:
        print("Both party JSON files already exist.  Use --force to refresh votes.")
        print(f"  {nat_path}")
        print(f"  {ind_path}")
        return

    print("Fetching national summary (00.json) …")
    data = fetch_summary()
    print("  OK")

    nat_parties = build_party_list(data, cam_id=0, prefix="party_")
    ind_parties = build_party_list(data, cam_id=4, prefix="indig_")

    print(f"  Nacional:  {len(nat_parties)} parties")
    print(f"  Indígena:  {len(ind_parties)} parties")

    if not nat_parties and not ind_parties:
        print("WARNING: no parties found in API response — check endpoint / cam values")
        return

    # Merge preserves existing colors when --force is used on already-colored files
    nat_out = merge_preserve_colors(nat_path, nat_parties)
    ind_out = merge_preserve_colors(ind_path, ind_parties)

    with open(nat_path, "w") as f:
        json.dump(nat_out, f, ensure_ascii=False, indent=2)
    print(f"Saved → {nat_path.name}  ({len(nat_out)} parties)")

    with open(ind_path, "w") as f:
        json.dump(ind_out, f, ensure_ascii=False, indent=2)
    print(f"Saved → {ind_path.name}  ({len(ind_out)} parties)")

    print("\nNext step: manually set 'color' for each party, then run the scraper.")


if __name__ == "__main__":
    main()
