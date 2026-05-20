"""
07_seat_allocation.py
Compute Colombia Senado 2026 seat distribution.

Nacional:  100 seats, 3% of valid votes threshold, D'Hondt method.
Indígena:    2 seats, D'Hondt among indigenous parties (no threshold).
Oposición:   1 seat, assigned post-presidential runoff (TBD).

Outputs:
  colombia/data/processed/senate_seats.json
"""

import json
import pandas as pd
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "processed"
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


def parse_candidates(code: str, nat_cands: pd.Series, list_type: str) -> list[dict]:
    """Build ranked candidate list for a party from aggregated national cand_ series."""
    prefix = f"cand_{code}_"
    party_series = {col: int(val) for col, val in nat_cands.items()
                    if col.startswith(prefix) and not col.endswith("|SOLO POR LA LISTA") and int(val) >= 0}

    candidates = []
    for col, votes in party_series.items():
        # col format: cand_XXXX_YYYYYY|Firstname Lastname
        rest = col[len(prefix):]                      # "YYYYYY|Name"
        pipe = rest.index("|") if "|" in rest else len(rest)
        codcan = int(rest[:pipe])
        name = rest[pipe + 1:] if "|" in rest else ""
        if codcan == 0 or not name:                   # skip SOLO POR LA LISTA
            continue
        candidates.append({"codcan": codcan, "name": name, "votes": votes})

    if list_type == "closed":
        candidates.sort(key=lambda c: c["codcan"])
    else:
        candidates.sort(key=lambda c: -c["votes"])

    # Drop codcan from output (frontend doesn't need it)
    return [{"rank": i + 1, "name": c["name"], "votes": c["votes"]} for i, c in enumerate(candidates)]


def main():
    with open(OUT / "national_parties.json") as f:
        all_parties = json.load(f)          # nacional only (indig already separated)

    with open(OUT / "indigena_parties.json") as f:
        indig_parties = json.load(f)

    with open(OUT / "parties.json") as f:
        party_lookup = json.load(f)         # for color overrides

    # True total valid votes = party votes + blank votes (blanks are valid in Colombia)
    nacional_csv = pd.read_csv(OUT / "resultados_nacional.csv")
    true_total_valid = int(nacional_csv["votos_validos"].iloc[0])
    votos_blanco_nacional = int(nacional_csv["votos_blanco"].iloc[0])

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
        "MOVIMIENTO ALTERNATIVO INDÍGENA Y SOCIAL \"MAIS\"":    "#B45309",
        "MOVIMIENTO AUTORIDADES INDÍGENAS DE COLOMBIA \"AICO\"":"#92400E",
        "MOVIMIENTO UNIDAD EN MINGA POR COLOMBIA":              "#78350F",
    }

    def color(nombre, fallback):
        return COLOUR_OVERRIDES.get(nombre, fallback)

    # ── Nacional seat allocation ──────────────────────────────────────────────
    # Use true total_valid from the nacional CSV (includes blank votes)
    # Threshold is computed against total valid votes (party votes + blanks)
    total_valid = true_total_valid
    threshold_votes = total_valid * THRESHOLD_PCT / 100

    qualifying = [p for p in all_parties if p["votes"] >= threshold_votes]
    votes_map = {p["code"]: p["votes"] for p in qualifying}
    seats_map = dhondt(votes_map, SEATS_NACIONAL)

    print(f"Total valid (nacional): {total_valid:,}")
    print(f"3% threshold:           {threshold_votes:,.0f}")
    print(f"Qualifying parties:     {len(qualifying)}")

    # ── Candidate aggregation ─────────────────────────────────────────────────
    print("Loading puestos for candidate aggregation …")
    df = pd.read_csv(OUT / "resultados_puestos.csv", dtype={"puesto_code": str})
    cand_cols  = [c for c in df.columns if c.startswith("cand_")]
    icand_cols = [c for c in df.columns if c.startswith("icand_")]
    nat_cands  = df[cand_cols].sum()
    ind_cands  = df[icand_cols].sum()

    # Detect list type: closed if ≥80% of candidate votes are in SOLO POR LA LISTA
    def detect_list_type(code: str) -> str:
        solo = next((v for col, v in nat_cands.items()
                     if col.startswith(f"cand_{code}_000000")), 0)
        total = sum(v for col, v in nat_cands.items()
                    if col.startswith(f"cand_{code}_") and v > 0)
        return "closed" if total > 0 and (solo / total) >= 0.80 else "open"

    # ── Build output ──────────────────────────────────────────────────────────
    parties_out = []
    for p in qualifying:
        code = p["code"]
        nombre = p["nombre"]
        lt = detect_list_type(code)
        cands = parse_candidates(code, nat_cands, lt)
        n_seats = seats_map[code]

        # Mark elected candidates
        for i, c in enumerate(cands):
            c["elected"] = i < n_seats

        parties_out.append({
            "code":       code,
            "nombre":     nombre,
            "color":      color(nombre, p["color"]),
            "votes":      p["votes"],
            "vote_pct":   round(p["votes"] / total_valid * 100, 2),
            "seats":      n_seats,
            "list_type":  lt,
            "candidates": cands,
        })
        print(f"  {nombre[:45]:45s}  {p['votes']:>10,}  {n_seats:>3} seats  {lt}")

    # ── Indígena ──────────────────────────────────────────────────────────────
    ind_total = sum(p["votes"] for p in indig_parties)
    ind_votes_map = {p["code"]: p["votes"] for p in indig_parties}
    ind_seats_map = dhondt(ind_votes_map, SEATS_INDIGENA)

    # Detect indigenous list type using icand_ columns (same 80% rule)
    def detect_ind_list_type(code: str) -> str:
        solo = next((v for col, v in ind_cands.items()
                     if col.startswith(f"icand_{code}_000000")), 0)
        total = sum(v for col, v in ind_cands.items()
                    if col.startswith(f"icand_{code}_") and v > 0)
        return "closed" if total > 0 and (solo / total) >= 0.80 else "open"

    def parse_ind_candidates(code: str, list_type: str) -> list[dict]:
        prefix = f"icand_{code}_"
        party_series = {col: int(val) for col, val in ind_cands.items()
                        if col.startswith(prefix) and int(val) >= 0}
        candidates = []
        for col, votes in party_series.items():
            rest = col[len(prefix):]
            pipe = rest.index("|") if "|" in rest else len(rest)
            codcan = int(rest[:pipe])
            name = rest[pipe + 1:] if "|" in rest else ""
            if codcan == 0 or not name:
                continue
            candidates.append({"codcan": codcan, "name": name, "votes": votes})
        if list_type == "closed":
            candidates.sort(key=lambda c: c["codcan"])
        else:
            candidates.sort(key=lambda c: -c["votes"])
        return [{"rank": i + 1, "name": c["name"], "votes": c["votes"]} for i, c in enumerate(candidates)]

    indigena_out = []
    for p in indig_parties:
        code = p["code"]
        n = ind_seats_map[code]
        if n == 0 and p["votes"] / ind_total < 0.05:
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
            "vote_pct":   round(p["votes"] / ind_total * 100, 2),
            "seats":      n,
            "list_type":  lt,
            "candidates": cands,
        })

    print(f"\nIndígena ({ind_total:,} valid votes):")
    for p in indigena_out:
        print(f"  {p['nombre'][:45]:45s}  {p['votes']:>8,}  {p['seats']} seat(s)  {p['list_type']}")

    # ── Write output ──────────────────────────────────────────────────────────
    out = {
        "total_valid":          total_valid,
        "votos_blanco_nacional": votos_blanco_nacional,
        "threshold_pct":        THRESHOLD_PCT,
        "threshold_votes":      round(threshold_votes),
        "seats_total":          103,
        "seats_nacional":       SEATS_NACIONAL,
        "seats_indigena":       SEATS_INDIGENA,
        "seats_oposicion":      1,
        "parties":              parties_out,
        "indigena":             indigena_out,
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
