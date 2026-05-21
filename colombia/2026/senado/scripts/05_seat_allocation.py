"""
05_seat_allocation.py
Compute Colombia Senado 2026 seat distribution.

Nacional:  100 seats, 3% of valid votes threshold, D'Hondt method.
Indígena:    2 seats, D'Hondt among indigenous parties (no threshold).
Oposición:   1 seat, assigned post-presidential runoff (TBD).

Outputs:
  data/senate_seats.json
"""

import csv
import json
import pandas as pd
from pathlib import Path

OUT      = Path(__file__).parent.parent / "data"
RESULTS  = OUT / "results"
METADATA = Path(__file__).parent.parent.parent / "metadata"
THRESHOLD_PCT = 3.0
SEATS_NACIONAL = 100
SEATS_INDIGENA = 2


def dhondt(votes_by_party: dict, seats: int) -> dict[str, int]:
    """Return {party_code: seats} via D'Hondt."""
    allocated = {k: 0 for k in votes_by_party}
    for _ in range(seats):
        quotients = {k: v / (allocated[k] + 1) for k, v in votes_by_party.items()}
        winner = max(quotients, key=quotients.get)
        allocated[winner] += 1
    return allocated


def parse_candidates(code: str, pref_rows: list[dict], list_type: str) -> list[dict]:
    """Build ranked candidate list for a party from the preferencial CSV rows."""
    party_rows = [r for r in pref_rows
                  if r["party_code"] == code.zfill(4)
                  and r["candidate_code"] != "000000"
                  and r["candidate_name"] not in ("", "SOLO POR LA LISTA")]
    candidates = [
        {"codcan": int(r["candidate_code"]), "name": r["candidate_name"], "votes": r["votes"]}
        for r in party_rows if r["votes"] >= 0
    ]
    if list_type == "closed":
        candidates.sort(key=lambda c: c["codcan"])
    else:
        candidates.sort(key=lambda c: -c["votes"])
    # Drop codcan from output (frontend doesn't need it)
    return [{"rank": i + 1, "name": c["name"], "votes": c["votes"]} for i, c in enumerate(candidates)]


def main():
    with open(OUT / "national_parties.json") as f:
        all_parties = json.load(f)

    with open(OUT / "indigena_parties.json") as f:
        indig_parties = json.load(f)

    # ── Load municipio CSVs for stats + candidate aggregation ────────────────
    print("Loading municipio results …")
    nat_df = pd.read_csv(RESULTS / "colombia_2026_municipio_senado_nacional.csv", dtype=str)
    ind_df = pd.read_csv(RESULTS / "colombia_2026_municipio_senado_indigena.csv", dtype=str)

    # Numeric columns — nacional
    _num_nat = ["votantes", "votos_validos", "votos_blanco", "votos_nulos",
                "votos_no_marcados", "mesas_total", "mesas_escrutadas",
                "ind_votantes", "ind_votos_validos", "ind_votos_blanco", "ind_votos_nulos"]
    for c in _num_nat:
        if c in nat_df.columns:
            nat_df[c] = pd.to_numeric(nat_df[c], errors="coerce").fillna(0)

    # Party vote columns — aggregate from CSV (source of truth for votes)
    party_cols = [c for c in nat_df.columns if c.startswith("party_")]
    indig_cols = [c for c in ind_df.columns if c.startswith("indig_")]
    for c in party_cols:
        nat_df[c] = pd.to_numeric(nat_df[c], errors="coerce").fillna(0)
    for c in indig_cols:
        ind_df[c] = pd.to_numeric(ind_df[c], errors="coerce").fillna(0)

    # Build vote totals from CSV — overrides any cached values in the party JSONs
    nat_votes_from_csv = {
        col.replace("party_", ""): int(nat_df[col].sum()) for col in party_cols
    }
    ind_votes_from_csv = {
        col.replace("indig_", ""): int(ind_df[col].sum()) for col in indig_cols
    }

    # Inject CSV-derived votes into the party lists
    for p in all_parties:
        p["votes"] = nat_votes_from_csv.get(str(p["code"]).zfill(4), 0)
    for p in indig_parties:
        p["votes"] = ind_votes_from_csv.get(str(p["code"]).zfill(4), 0)

    # ── Load preferencial CSVs (candidate votes, nationally aggregated) ─────
    # These files are absent in mock mode — functions gracefully return empty lists.
    def load_pref(path: Path) -> list[dict]:
        if not path.exists():
            print(f"  (no preferencial CSV at {path.name} — skipping candidates)")
            return []
        with open(path) as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            r["votes"] = int(r.get("votes") or 0)
        return rows

    nat_pref = load_pref(RESULTS / "colombia_2026_senado_nacional_preferencial.csv")
    ind_pref = load_pref(RESULTS / "colombia_2026_senado_indigena_preferencial.csv")

    # Vote totals for threshold and seat allocation — from CSVs only
    nac_validos = int(nat_df["votos_validos"].sum())
    ind_validos = int(nat_df["ind_votos_validos"].sum())

    # Colour overrides (nomenclator colours are often wrong)
    COLOUR_OVERRIDES = {
        "PACTO HISTÓRICO SENADO":                               "#6B21A8",
        "MOVIMIENTO POLÍTICO PACTO HISTÓRICO":                  "#6B21A8",
        "PARTIDO CENTRO DEMOCRÁTICO":                           "#1D4ED8",
        "PARTIDO LIBERAL COLOMBIANO":                           "#DC2626",
        "PARTIDO CONSERVADOR COLOMBIANO":                       "#1E40AF",
        "ALIANZA POR COLOMBIA":                                 "#15803D",
        "PARTIDO DE LA UNIÓN POR LA GENTE - PARTIDO DE LA U":  "#D97706",
        "COALICIÓN CAMBIO RADICAL - ALMA":                      "#EA580C",
        "PARTIDO CAMBIO RADICAL":                               "#EA580C",
        "AHORA COLOMBIA":                                       "#BE185D",
        "MOVIMIENTO SALVACIÓN NACIONAL":                        "#7C3AED",
        "MOVIMIENTO ALTERNATIVO INDÍGENA Y SOCIAL \"MAIS\"":    "#0F766E",
        "MOVIMIENTO AUTORIDADES INDÍGENAS DE COLOMBIA \"AICO\"":"#9A3412",
        "MOVIMIENTO UNIDAD EN MINGA POR COLOMBIA":              "#6D28D9",
    }

    def color(nombre, fallback):
        return COLOUR_OVERRIDES.get(nombre, fallback)

    # ── Nacional seat allocation ──────────────────────────────────────────────
    # Threshold computed against total valid (nat+ext, incl. blanks)
    total_valid = nac_validos
    threshold_votes = total_valid * THRESHOLD_PCT / 100

    qualifying = [p for p in all_parties if p["votes"] >= threshold_votes]
    votes_map = {p["code"]: p["votes"] for p in qualifying}
    seats_map = dhondt(votes_map, SEATS_NACIONAL)

    print(f"Total valid (nacional): {total_valid:,}")
    print(f"3% threshold:           {threshold_votes:,.0f}")
    print(f"Qualifying parties:     {len(qualifying)}")

    # Detect list type: closed if ≥80% of candidate votes are in SOLO POR LA LISTA
    def detect_list_type(code: str) -> str:
        party_rows = [r for r in nat_pref if r["party_code"] == code.zfill(4)]
        solo  = sum(r["votes"] for r in party_rows if r["candidate_code"] == "000000")
        total = sum(r["votes"] for r in party_rows if r["votes"] > 0)
        return "closed" if total > 0 and (solo / total) >= 0.80 else "open"

    # ── Build output ──────────────────────────────────────────────────────────
    parties_out = []
    for p in qualifying:
        code = p["code"]
        nombre = p["nombre"]
        lt = detect_list_type(code)
        cands = parse_candidates(code, nat_pref, lt)
        n_seats = seats_map[code]

        # Mark elected candidates
        for i, c in enumerate(cands):
            c["elected"] = i < n_seats

        parties_out.append({
            "code":       code,
            "nombre":     nombre,
            "color":      color(nombre, p["color"]),
            "votes":      p["votes"],
            "vote_pct":   round(p["votes"] / total_valid * 100, 2) if total_valid else 0.0,
            "seats":      n_seats,
            "list_type":  lt,
            "candidates": cands,
        })
        print(f"  {nombre[:45]:45s}  {p['votes']:>10,}  {n_seats:>3} seats  {lt}")

    # ── Indígena ──────────────────────────────────────────────────────────────
    ind_total = sum(p["votes"] for p in indig_parties)
    ind_votes_map = {p["code"]: p["votes"] for p in indig_parties}
    ind_seats_map = dhondt(ind_votes_map, SEATS_INDIGENA)

    # Detect indigenous list type using ind_pref (same 80% rule)
    def detect_ind_list_type(code: str) -> str:
        party_rows = [r for r in ind_pref if r["party_code"] == code.zfill(4)]
        solo  = sum(r["votes"] for r in party_rows if r["candidate_code"] == "000000")
        total = sum(r["votes"] for r in party_rows if r["votes"] > 0)
        return "closed" if total > 0 and (solo / total) >= 0.80 else "open"

    def parse_ind_candidates(code: str, list_type: str) -> list[dict]:
        return parse_candidates(code, ind_pref, list_type)

    indigena_out = []
    for p in indig_parties:
        code = p["code"]
        n = ind_seats_map[code]
        if n == 0 and (ind_total == 0 or p["votes"] / ind_total < 0.05):
            continue                 # omit tiny parties with no seats
        lt = detect_ind_list_type(code)
        cands = parse_ind_candidates(code, lt)
        for i, c in enumerate(cands):
            c["elected"] = i < n
        indigena_out.append({
            "code":       code,
            "nombre":     p["nombre"],
            "color":      color(p["nombre"], p["color"]),
            "votes":      p["votes"],
            "vote_pct":   round(p["votes"] / ind_total * 100, 2) if ind_total else 0.0,
            "seats":      n,
            "list_type":  lt,
            "candidates": cands,
        })

    print(f"\nIndígena ({ind_total:,} valid votes):")
    for p in indigena_out:
        print(f"  {p['nombre'][:45]:45s}  {p['votes']:>8,}  {p['seats']} seat(s)  {p['list_type']}")

    # ── All-parties lists (for frontend sidebar — includes non-qualifying parties) ──
    # Votes come from CSV; sorted by votes desc.  Partido JSONs are metadata-only.
    all_parties_out = sorted(
        [{"code": p["code"], "nombre": p["nombre"], "color": color(p["nombre"], p["color"]),
          "votes": p["votes"]}
         for p in all_parties],
        key=lambda x: -x["votes"]
    )
    all_indigena_out = sorted(
        [{"code": p["code"], "nombre": p["nombre"], "color": color(p["nombre"], p["color"]),
          "votes": p["votes"]}
         for p in indig_parties],
        key=lambda x: -x["votes"]
    )

    # ── Write output ──────────────────────────────────────────────────────────
    # senate_seats.json contains ONLY seat allocation results.
    # All map/header stats (votantes, censo, mesas, votos_validos) are computed
    # by the frontend directly from the GeoJSON features it already loads.
    out = {
        "threshold_pct":   THRESHOLD_PCT,
        "threshold_votes": round(threshold_votes),
        "total_valid":     total_valid,
        "seats_total":     103,
        "seats_nacional":  SEATS_NACIONAL,
        "seats_indigena":  SEATS_INDIGENA,
        "seats_oposicion": 1,
        "all_parties":     all_parties_out,
        "all_indigena":    all_indigena_out,
        "parties":         parties_out,
        "indigena":        indigena_out,
        "oposicion": {
            "seats": 1,
            "note":  "Estatuto de la Oposición — asignado tras segunda vuelta presidencial"
        },
    }

    path = OUT / "senate_seats.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved → {path}")
    print(f"Total seats allocated: {sum(p['seats'] for p in parties_out)} + {SEATS_INDIGENA} + 1 = "
          f"{sum(p['seats'] for p in parties_out) + SEATS_INDIGENA + 1}")


if __name__ == "__main__":
    main()
