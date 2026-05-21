"""
04_build_mesa_electoral_roll.py
Build colombia_2026_mesa_electoral_roll.csv from nomenclator.json.

Mesa codes are fully deterministic:
  mesa_code = puesto_code (13 chars) + mesa_num zero-padded to 6 digits (19 chars total)

No network scraping is needed — the Registraduría nomenclator already contains
num_mesas per puesto. This script simply expands the puesto list into individual
mesa rows and annotates each with the full geographic hierarchy.

Output: colombia/2026/metadata/colombia_2026_mesa_electoral_roll.csv
Columns:
  mesa_code        — 19-char unique mesa identifier
  puesto_code      — 13-char puesto (voting location) code
  mesa_num         — integer mesa number within the puesto (1-based)
  puesto_name
  zona_code
  zona_name
  mpio_reg_code_7
  mpio_name
  dept_reg_code
  dept_name
  is_exterior      — True for overseas circunscripciones (dept_reg_code starts with 88)
"""

import json
import pandas as pd
from pathlib import Path

RAW = Path(__file__).parent.parent / "raw"
OUT = Path(__file__).parent.parent   # outputs directly into metadata/


def build_mesa_roll() -> pd.DataFrame:
    print("Loading nomenclator.json …")
    with open(RAW / "nomenclator.json") as f:
        data = json.load(f)

    # elec=1 → Senado (contains all circunscripciones, including exterior)
    amb_senado = next(a for a in data["amb"] if a["elec"] == 1)
    ambitos = amb_senado["ambitos"]
    by_i = {a["i"]: a for a in ambitos}

    def get_parent(node, target_level):
        """Walk parent links up to target_level; return first match or None."""
        for parent_group in node.get("p", []):
            if parent_group["l"] == target_level:
                for pi in parent_group["p"]:
                    return by_i.get(pi)
        return None

    # Level 6 = puesto (voting location)
    puestos = [a for a in ambitos if a["l"] == 6]
    print(f"  Total puestos: {len(puestos):,}")

    rows = []
    for p in puestos:
        code      = p["c"]          # 13-char puesto code
        num_mesas = int(p.get("m") or 0)
        if num_mesas == 0:
            continue                # skip puestos with no mesas (shouldn't happen)

        zona_node = get_parent(p, 4)
        mpio_node = get_parent(zona_node, 3) if zona_node else None
        dept_node = get_parent(mpio_node, 2) if mpio_node else None

        dept_reg_code   = code[0:4]
        mpio_reg_code_7 = code[0:7]
        zona_code       = code[0:9]
        is_exterior     = dept_reg_code.startswith("88")

        for i in range(1, num_mesas + 1):
            rows.append({
                "mesa_code":        f"{code}{i:06d}",
                "puesto_code":      code,
                "mesa_num":         i,
                "puesto_name":      p["n"],
                "zona_code":        zona_code,
                "zona_name":        zona_node["n"] if zona_node else "",
                "mpio_reg_code_7":  mpio_reg_code_7,
                "mpio_name":        mpio_node["n"] if mpio_node else "",
                "dept_reg_code":    dept_reg_code,
                "dept_name":        dept_node["n"] if dept_node else "",
                "is_exterior":      is_exterior,
            })

    df = pd.DataFrame(rows)

    national = df[~df["is_exterior"]].shape[0]
    exterior = df[ df["is_exterior"]].shape[0]
    print(f"  National mesas: {national:,}")
    print(f"  Exterior mesas: {exterior:,}")
    print(f"  Total mesas:    {len(df):,}")

    out_path = OUT / "colombia_2026_mesa_electoral_roll.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    build_mesa_roll()
