"""
01_build_candidate_jsons.py — ONE-TIME initializer for primarias metadata JSONs.

Fetches the national CN summary (codpar 30/31/32 = the three consultas) and
produces four JSON files:

  data/soluciones_candidates.json   ← candidates of Consulta de las Soluciones (codpar 30)
  data/gran_candidates.json         ← candidates of Gran Consulta por Colombia  (codpar 31)
  data/frente_candidates.json       ← candidates of Frente por la Vida          (codpar 32)
  data/interconsultas_parties.json  ← the three consultas treated as "parties"

Existing files are NOT overwritten unless --force is passed.
After running, manually set "color" and optionally "image_id" for each entry;
subsequent scrapes will never touch those fields.

Usage:
  python3 scripts/01_build_candidate_jsons.py
  python3 scripts/01_build_candidate_jsons.py --force   # regenerate (preserves colors)
"""

import argparse
import json
import ssl
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT = SCRIPT_DIR.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

API_URL = (
    "https://resultadospreccongreso2026.registraduria.gov.co/json/ACT/CN/00.json"
)
HEADERS = {
    "Referer":    "https://resultadospreccongreso2026.registraduria.gov.co/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# Hardcoded mapping: codpar → consulta metadata (nompar is None in the API)
CONSULTA_META = {
    30: {
        "slug":     "soluciones",
        "nombre":   "Consulta de las Soluciones",
        "color":    "#7C3AED",   # default — edit after generation
    },
    31: {
        "slug":     "gran",
        "nombre":   "Gran Consulta por Colombia",
        "color":    "#1D4ED8",
        "color":    "#1D4ED8",
    },
    32: {
        "slug":     "frente",
        "nombre":   "Frente por la Vida",
        "color":    "#D97706",
    },
}

# Default candidate colors per consulta (cycle if more candidates than colors)
DEFAULT_CAND_COLORS = {
    "soluciones": ["#7C3AED", "#A855F7", "#C084FC", "#DDA0DD"],
    "gran":       ["#1D4ED8", "#2563EB", "#3B82F6", "#60A5FA",
                   "#93C5FD", "#BFDBFE", "#1E40AF", "#3730A3", "#4F46E5"],
    "frente":     ["#D97706", "#F59E0B", "#FBBF24", "#FCD34D", "#FDE68A"],
}


def fetch_national() -> dict:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read())


def build_candidates(data: dict, codpar: int) -> list[dict]:
    """Extract and sort candidates for one consulta from the national summary."""
    meta  = CONSULTA_META[codpar]
    slug  = meta["slug"]
    colors = DEFAULT_CAND_COLORS.get(slug, ["#888"])

    candidates = []
    for cam in data.get("camaras", []):
        if int(cam.get("cam", -1)) != 0:
            continue
        for pw in cam.get("partotabla", []):
            p = pw.get("act", pw)
            if int(p.get("codpar", -1)) != codpar:
                continue
            for cand in p.get("cantotabla", []):
                cod  = str(int(cand.get("codcan", 0))).zfill(6)
                nom  = f"{cand.get('nomcan','').strip()} {cand.get('apecan','').strip()}".strip()
                vot  = int(cand.get("vot") or 0)
                candidates.append({"code": cod, "nombre": nom, "votes_nat": vot})

    candidates.sort(key=lambda c: -c["votes_nat"])

    out = []
    for i, c in enumerate(candidates):
        out.append({
            "code":     c["code"],
            "nombre":   c["nombre"],
            "partido":  meta["nombre"],
            "color":    colors[i % len(colors)],
            "image_id": None,   # fill manually when photos are available
        })
    return out


def build_interconsultas(data: dict) -> list[dict]:
    """Build the three consultas as 'parties' for the interconsultas view."""
    out = []
    for codpar, meta in sorted(CONSULTA_META.items()):
        # Count national votes for this consulta
        total = 0
        for cam in data.get("camaras", []):
            if int(cam.get("cam", -1)) != 0:
                continue
            for pw in cam.get("partotabla", []):
                p = pw.get("act", pw)
                if int(p.get("codpar", -1)) == codpar:
                    total = int(p.get("vot") or 0)
        out.append({
            "code":         str(codpar),
            "slug":         meta["slug"],
            "nombre":       meta["nombre"],
            "display_name": meta["nombre"],
            "color":        meta["color"],
            "votes_nat":    total,
        })
    return sorted(out, key=lambda x: -x["votes_nat"])


def merge_preserve(existing_path: Path, new_entries: list[dict],
                   key: str = "code") -> list[dict]:
    """Keep colors / image_ids from an existing file; add new entries."""
    if not existing_path.exists():
        return new_entries
    with open(existing_path) as f:
        existing = {str(e[key]): e for e in json.load(f)}
    merged = {}
    for e in new_entries:
        k = str(e[key])
        if k in existing:
            saved = existing[k]
            e["color"]    = saved.get("color",    e["color"])
            e["image_id"] = saved.get("image_id", e.get("image_id"))
            if "display_name" in saved:
                e["display_name"] = saved["display_name"]
        merged[k] = e
    return list(merged.values())


def save(path: Path, data: list[dict], label: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved → {path.name}  ({len(data)} entries)  [{label}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files exist (colors / image_ids preserved)")
    args = parser.parse_args()

    paths = {
        "soluciones": OUT / "soluciones_candidates.json",
        "gran":       OUT / "gran_candidates.json",
        "frente":     OUT / "frente_candidates.json",
        "inter":      OUT / "interconsultas_parties.json",
    }

    all_exist = all(p.exists() for p in paths.values())
    if all_exist and not args.force:
        print("All candidate/party JSON files already exist. Use --force to refresh.")
        for p in paths.values():
            print(f"  {p}")
        return

    print("Fetching national CN summary …")
    data = fetch_national()
    print("  OK")

    # Per-consulta candidates
    for codpar, meta in CONSULTA_META.items():
        slug  = meta["slug"]
        path  = paths[slug]
        cands = build_candidates(data, codpar)
        if args.force:
            cands = merge_preserve(path, cands)
        save(path, cands, slug)

    # Interconsultas parties
    inter = build_interconsultas(data)
    if args.force:
        inter = merge_preserve(paths["inter"], inter)
    save(paths["inter"], inter, "interconsultas")

    print("\nNext step: edit 'color' and optionally 'image_id' in each JSON,")
    print("then run 02_scrape_municipios.py to fetch municipal results.")


if __name__ == "__main__":
    main()
