"""
00_mock_results.py — Generate mock result CSVs for pre-election / UI testing.

Produces:
  data/results/colombia_2026_municipio_primera.csv  (1,189 rows, one per municipio)
  data/results/colombia_2026_mesa_primera.csv       (126,647 rows, one per mesa)

By default all vote / candidate columns are 0.
No 'mesas_total' or 'censo' columns in the municipio CSV → the GeoJSON builder
and aggregate-stats script fall back on the electoral roll for those values.

Flags:
  --random FRACTION   Fill vote columns with random numbers scaled so that
                      total turnout ≈ FRACTION × total censo.
                      E.g. --random 0.3 simulates ~30 % turnout nationwide.
                      Only the municipio CSV gets random votes; mesa CSV stays
                      all-zeros (no per-mesa random mode needed for UI testing).
  --seed SEED         Random seed for reproducibility (default: 42).
  --overwrite         Replace existing files (default: skip if they exist).

Usage:
  python3 scripts/00_mock_results.py
  python3 scripts/00_mock_results.py --random 0.3 --overwrite
"""

import argparse
import csv
import json
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
METADATA   = SCRIPT_DIR.parent.parent / "metadata"
OUT        = SCRIPT_DIR.parent / "data"
RESULTS    = OUT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

MPIO_ROLL_CSV = METADATA / "colombia_2026_municipio_electoral_roll.csv"
MESA_ROLL_CSV = METADATA / "colombia_2026_mesa_electoral_roll.csv"
CANDS_JSON    = OUT / "candidates.json"

MPIO_OUT = RESULTS / "colombia_2026_municipio_primera.csv"
MESA_OUT = RESULTS / "colombia_2026_mesa_primera.csv"

CAND_CODES = [
    "cepeda", "valencia", "delaespriella", "claudialopez", "barreras",
    "fajardo", "caicedo", "lizcano", "uribe", "botero",
    "macollins", "matamoros", "claralopez",
]


def load_cand_codes() -> list[str]:
    """Return candidate codes in JSON order (fallback to hardcoded list)."""
    if CANDS_JSON.exists():
        with open(CANDS_JSON) as f:
            return [c["code"] for c in json.load(f)]
    return CAND_CODES


def build_votes(censo: int, fraction: float, rng: random.Random) -> dict:
    """
    Generate vote breakdown for a single municipio row.
    fraction — target turnout (votantes / censo); each municipio gets a small
    random ±jitter so the distribution looks organic.
    """
    if censo <= 0 or fraction <= 0:
        return {}

    jitter   = rng.uniform(-0.25 * fraction, 0.25 * fraction)
    turnout  = max(0.05, min(0.95, fraction + jitter))
    votantes = int(censo * turnout)

    nulos_r   = rng.uniform(0.018, 0.055)
    no_marc_r = rng.uniform(0.004, 0.018)
    blank_r   = rng.uniform(0.018, 0.075)

    votos_nulos       = int(votantes * nulos_r)
    votos_no_marcados = int(votantes * no_marc_r)
    votos_validos     = votantes - votos_nulos - votos_no_marcados
    votos_blanco      = int(votos_validos * blank_r)

    return {
        "votantes":          votantes,
        "votos_nulos":       votos_nulos,
        "votos_no_marcados": votos_no_marcados,
        "votos_blanco":      votos_blanco,
        "votos_validos":     votos_validos,
    }


def distribute_cand_votes(votos_validos: int, votos_blanco: int,
                          cand_cols: list[str], rng: random.Random) -> dict[str, int]:
    """
    Split (votos_validos − votos_blanco) among candidates with Dirichlet-like
    exponential weights. Rounding remainder goes to the last candidate.
    """
    to_split = max(0, votos_validos - votos_blanco)
    if not cand_cols or to_split == 0:
        return {c: 0 for c in cand_cols}

    weights   = [rng.expovariate(1.0) for _ in cand_cols]
    total_w   = sum(weights)
    result    = {}
    remaining = to_split
    for col, w in zip(cand_cols[:-1], weights[:-1]):
        v = int(to_split * w / total_w)
        result[col] = v
        remaining  -= v
    result[cand_cols[-1]] = max(0, remaining)
    return result


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved → {path.name}  ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate mock primera vuelta result CSVs")
    parser.add_argument(
        "--random", type=float, metavar="FRACTION", default=None,
        help=("Simulate turnout at FRACTION of censo (e.g. 0.3 = 30 %%). "
              "Votes distributed randomly among candidates. "
              "Omit for all-zero empty CSVs."))
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

    skip_mpio = MPIO_OUT.exists() and not args.overwrite
    skip_mesa = MESA_OUT.exists() and not args.overwrite
    if skip_mpio and skip_mesa:
        print("Both result files already exist — use --overwrite to replace.")
        return
    if skip_mpio:
        print(f"  Skipping {MPIO_OUT.name} (exists; use --overwrite)")
    if skip_mesa:
        print(f"  Skipping {MESA_OUT.name} (exists; use --overwrite)")

    cand_codes = load_cand_codes()
    cand_cols  = [f"cand_{c}" for c in cand_codes]

    mode = f"random ({args.random:.0%} turnout)" if args.random is not None else "zero"
    print(f"Mode: {mode}")

    # ── Municipio CSV ─────────────────────────────────────────────────────────
    # No 'mesas_total' or 'censo' columns → GeoJSON/aggregate-stats fall back
    # to the electoral roll metadata for those values.
    mpio_fields = (
        ["mpio_reg_code_7",
         "votantes", "votos_nulos", "votos_no_marcados", "votos_blanco", "votos_validos",
         "mesas_escrutadas"]
        + cand_cols
    )

    with open(MPIO_ROLL_CSV) as f:
        mpio_roll = list(csv.DictReader(f))
    print(f"Loaded {len(mpio_roll)} municipios from electoral roll.")

    mpio_rows = []
    for mpio in mpio_roll:
        row = {f: 0 for f in mpio_fields}
        row["mpio_reg_code_7"] = mpio["mpio_reg_code_7"]

        if args.random is not None:
            censo = int(mpio.get("censo") or 0)
            vbase = build_votes(censo, args.random, rng)
            row.update(vbase)
            cvotes = distribute_cand_votes(
                row["votos_validos"], row["votos_blanco"], cand_cols, rng)
            row.update(cvotes)
            # Every municipio counts as 1 mesa escrutada in random mode
            row["mesas_escrutadas"] = 1

        mpio_rows.append(row)

    # ── Mesa CSV ──────────────────────────────────────────────────────────────
    # Mesa CSV stays all-zeros even in random mode — it's used only by the
    # Monte Carlo forecast, which handles the zero/empty state gracefully.
    # Schema matches 02b_scrape_mesas.py output exactly.
    mesa_fields = (
        ["mesa_code", "mpio_reg_code_7", "counted",
         "votantes", "votos_nulos", "votos_no_marcados",
         "votos_blanco", "votos_validos"]
        + cand_cols
    )

    with open(MESA_ROLL_CSV) as f:
        mesa_roll = list(csv.DictReader(f))
    print(f"Loaded {len(mesa_roll)} mesas from electoral roll.")

    mesa_rows = []
    for mesa in mesa_roll:
        row = {f: 0 for f in mesa_fields}
        row["mesa_code"]       = mesa["mesa_code"]
        row["mpio_reg_code_7"] = mesa["mpio_reg_code_7"]
        row["counted"]         = 0
        mesa_rows.append(row)

    print(f"\nWriting {mode} mock results …")
    if not skip_mpio:
        write_csv(MPIO_OUT, mpio_rows, mpio_fields)
    if not skip_mesa:
        write_csv(MESA_OUT, mesa_rows, mesa_fields)

    # Remove aggregate_stats.json and forecast.json so they are regenerated
    for stale in [OUT / "aggregate_stats.json", OUT / "forecast.json"]:
        if stale.exists():
            stale.unlink()
            print(f"  Removed {stale.name} (will be regenerated by pipeline)")

    print(f"\nDone. No 'mesas_total'/'censo' columns in municipio CSV →")
    print("GeoJSON builder + aggregate-stats fall back to electoral roll metadata.")


if __name__ == "__main__":
    main()
