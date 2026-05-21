"""
00_mock_results_municipio.py — Generate mock result CSVs for pre-election / UI testing.

Produces:
  data/results/colombia_2026_municipio_senado_nacional.csv
  data/results/colombia_2026_municipio_senado_indigena.csv

Rows come from the electoral roll (one per municipio).
All vote / party columns are 0 by default.
No 'censo' or 'mesas_total' columns → forces GeoJSON builder to fall back on
the metadata electoral roll for those values.

Flags:
  --random FRACTION   Fill vote columns with random numbers scaled so that
                      total national turnout ≈ FRACTION × total censo.
                      E.g. --random 0.3 simulates ~30 % turnout nationwide.
  --seed SEED         Random seed for reproducibility (default: 42).
  --overwrite         Replace existing files (default: skip if they exist).

Usage:
  python3 scripts/00_mock_results_municipio.py
  python3 scripts/00_mock_results_municipio.py --random 0.3 --overwrite
"""

import argparse
import csv
import json
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
METADATA   = SCRIPT_DIR.parent.parent / "metadata"    # colombia/2026/metadata/
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ROLL_CSV = METADATA / "colombia_2026_municipio_electoral_roll.csv"
NAT_JSON = OUT / "national_parties.json"
IND_JSON = OUT / "indigena_parties.json"

NAT_OUT = RESULTS / "colombia_2026_municipio_senado_nacional.csv"
IND_OUT = RESULTS / "colombia_2026_municipio_senado_indigena.csv"

# Indigena circunscripción is roughly 1–2 % of the nacional electorate
IND_FRAC_LO, IND_FRAC_HI = 0.004, 0.012


def load_roll() -> list[dict]:
    with open(ROLL_CSV) as f:
        return list(csv.DictReader(f))


def load_party_codes(path: Path, prefix: str) -> list[str]:
    """Return list of 'prefix_XXXX' column names ordered as in the JSON."""
    if not path.exists():
        return []
    with open(path) as f:
        parties = json.load(f)
    return [f"{prefix}{str(p['code']).zfill(4)}" for p in parties]


def build_votes(censo: int, fraction: float, rng: random.Random) -> dict:
    """
    Generate vote breakdown for a single row.

    fraction — target turnout (votantes / censo); each municipio gets a small
    random ±jitter around this so the distribution looks organic.
    """
    if censo <= 0 or fraction <= 0:
        return {}

    # Per-mpio jitter: ±25 % of the target fraction, clamped to [0.05, 0.95]
    jitter   = rng.uniform(-0.25 * fraction, 0.25 * fraction)
    turnout  = max(0.05, min(0.95, fraction + jitter))
    votantes = int(censo * turnout)

    # Breakdown ratios (mild randomness so individual mpios differ)
    nulos_r   = rng.uniform(0.018, 0.055)
    no_marc_r = rng.uniform(0.004, 0.018)
    blank_r   = rng.uniform(0.018, 0.075)

    votos_nulos        = int(votantes * nulos_r)
    votos_no_marcados  = int(votantes * no_marc_r)
    votos_validos      = votantes - votos_nulos - votos_no_marcados
    votos_blanco       = int(votos_validos * blank_r)

    return {
        "votantes":          votantes,
        "votos_nulos":       votos_nulos,
        "votos_no_marcados": votos_no_marcados,
        "votos_blanco":      votos_blanco,
        "votos_validos":     votos_validos,
    }


def distribute_party_votes(votos_validos: int, votos_blanco: int,
                           party_cols: list[str], rng: random.Random) -> dict[str, int]:
    """
    Split (votos_validos − votos_blanco) among parties with Dirichlet-like weights.
    Remaining votes after integer rounding go to the last party.
    """
    to_split = max(0, votos_validos - votos_blanco)
    if not party_cols or to_split == 0:
        return {c: 0 for c in party_cols}

    weights  = [rng.expovariate(1.0) for _ in party_cols]
    total_w  = sum(weights)
    result   = {}
    remaining = to_split
    for col, w in zip(party_cols[:-1], weights[:-1]):
        v = int(to_split * w / total_w)
        result[col] = v
        remaining  -= v
    result[party_cols[-1]] = max(0, remaining)
    return result


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved → {path.name}  ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate mock municipio result CSVs for Senado 2026")
    parser.add_argument(
        "--random", type=float, metavar="FRACTION", default=None,
        help=("Simulate turnout at FRACTION of censo (e.g. 0.3 = 30 %%). "
              "Votes are distributed randomly across parties. "
              "Omit flag for all-zero empty CSVs."))
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing files (default: skip if they already exist)")
    args = parser.parse_args()

    if args.random is not None and not (0 < args.random <= 1):
        parser.error("--random FRACTION must be between 0 (exclusive) and 1 (inclusive)")

    rng = random.Random(args.seed)

    # Column sets (ordered as in the party JSONs)
    party_cols = load_party_codes(NAT_JSON, "party_")
    indig_cols = load_party_codes(IND_JSON, "indig_")

    nat_fields = (
        ["mpio_reg_code_7",
         "votantes", "votos_nulos", "votos_no_marcados", "votos_blanco", "votos_validos",
         "mesas_escrutadas",
         "ind_votantes", "ind_votos_validos", "ind_votos_blanco", "ind_votos_nulos"]
        + party_cols
    )
    ind_fields = (
        ["mpio_reg_code_7",
         "votantes", "votos_nulos", "votos_no_marcados", "votos_blanco", "votos_validos",
         "mesas_escrutadas"]
        + indig_cols
    )

    # Overwrite guard
    skip_nat = NAT_OUT.exists() and not args.overwrite
    skip_ind = IND_OUT.exists() and not args.overwrite
    if skip_nat and skip_ind:
        print("Both result files already exist — use --overwrite to replace.")
        return
    if skip_nat:
        print(f"  Skipping {NAT_OUT.name} (exists; use --overwrite)")
    if skip_ind:
        print(f"  Skipping {IND_OUT.name} (exists; use --overwrite)")

    roll = load_roll()
    mode = f"random ({args.random:.0%} turnout)" if args.random is not None else "zero"
    print(f"Loaded {len(roll)} municipios from electoral roll. Mode: {mode}")

    nat_rows, ind_rows = [], []

    for mpio in roll:
        code  = mpio["mpio_reg_code_7"]
        censo = int(mpio.get("censo") or 0)

        # ── Nacional row ─────────────────────────────────────────────
        nat_row = {f: 0 for f in nat_fields}
        nat_row["mpio_reg_code_7"] = code

        if args.random is not None:
            vbase = build_votes(censo, args.random, rng)
            nat_row.update(vbase)
            pvotes = distribute_party_votes(
                nat_row["votos_validos"], nat_row["votos_blanco"], party_cols, rng)
            nat_row.update(pvotes)

            # Indigena aggregates stored in the nacional row (small fraction)
            ind_frac   = rng.uniform(IND_FRAC_LO, IND_FRAC_HI)
            ind_vot    = int(censo * ind_frac * args.random)
            ind_val    = int(ind_vot * rng.uniform(0.80, 0.90))
            ind_blk    = int(ind_val * rng.uniform(0.03, 0.08))
            ind_nul    = int(ind_vot * rng.uniform(0.02, 0.06))
            nat_row["ind_votantes"]      = ind_vot
            nat_row["ind_votos_validos"] = ind_val
            nat_row["ind_votos_blanco"]  = ind_blk
            nat_row["ind_votos_nulos"]   = ind_nul

        nat_rows.append(nat_row)

        # ── Indigena row ─────────────────────────────────────────────
        ind_row = {f: 0 for f in ind_fields}
        ind_row["mpio_reg_code_7"] = code

        if args.random is not None:
            ind_vot = nat_row["ind_votantes"]
            ind_val = nat_row["ind_votos_validos"]
            ind_blk = nat_row["ind_votos_blanco"]
            ind_nul = nat_row["ind_votos_nulos"]
            ind_nom = max(0, ind_vot - ind_val - ind_nul)
            ind_row["votantes"]          = ind_vot
            ind_row["votos_validos"]     = ind_val
            ind_row["votos_blanco"]      = ind_blk
            ind_row["votos_nulos"]       = ind_nul
            ind_row["votos_no_marcados"] = ind_nom
            ivotes = distribute_party_votes(ind_val, ind_blk, indig_cols, rng)
            ind_row.update(ivotes)

        ind_rows.append(ind_row)

    print(f"\nWriting {mode} mock results …")
    if not skip_nat:
        write_csv(NAT_OUT, nat_rows, nat_fields)
    if not skip_ind:
        write_csv(IND_OUT, ind_rows, ind_fields)

    # Remove preferencial CSVs — mock has no candidate data so these must not exist
    for pref in [
        RESULTS / "colombia_2026_senado_nacional_preferencial.csv",
        RESULTS / "colombia_2026_senado_indigena_preferencial.csv",
    ]:
        if pref.exists():
            pref.unlink()
            print(f"  Removed {pref.name} (not valid in mock mode)")

    print("\nDone. No 'censo' or 'mesas_total' columns → GeoJSON builder falls back")
    print("to electoral roll metadata for those values.")


if __name__ == "__main__":
    main()
