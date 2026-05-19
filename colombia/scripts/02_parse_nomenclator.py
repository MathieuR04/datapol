"""
02_parse_nomenclator.py
Parse nomenclator.json → puestos_master.csv (all puestos, elec=1 Senado).
Includes exterior (dept code 88xx). is_exterior flag set for those.
Output: colombia/data/processed/puestos_master.csv
"""

import json
import pandas as pd
from pathlib import Path

RAW = Path(__file__).parent.parent / "data" / "raw"
OUT = Path(__file__).parent.parent / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)


def parse_nomenclator():
    print("Loading nomenclator.json …")
    with open(RAW / "nomenclator.json") as f:
        data = json.load(f)

    # elec=1 → Senado
    amb_senado = next(a for a in data["amb"] if a["elec"] == 1)
    ambitos = amb_senado["ambitos"]
    # Index by position (ambitos is a list, h/p reference positions)
    by_i = {a["i"]: a for a in ambitos}

    # ── build parent lookups ──────────────────────────────────────────────────
    # Level 2 = dept
    depts = {a["i"]: a for a in ambitos if a["l"] == 2}
    # Level 3 = municipio
    mpios = {a["i"]: a for a in ambitos if a["l"] == 3}
    # Level 4 = zona
    zonas = {a["i"]: a for a in ambitos if a["l"] == 4}

    def get_parent(node, target_level):
        """Walk parent links up to target_level."""
        for parent_group in node.get("p", []):
            if parent_group["l"] == target_level:
                for pi in parent_group["p"]:
                    return by_i.get(pi)
        return None

    # ── extract level-6 puestos ───────────────────────────────────────────────
    rows = []
    puestos = [a for a in ambitos if a["l"] == 6]
    print(f"  Total level-6 puestos: {len(puestos)}")

    for p in puestos:
        code = p["c"]  # 13-char

        zona_node = get_parent(p, 4)
        mpio_node  = get_parent(zona_node, 3) if zona_node else None
        dept_node  = get_parent(mpio_node,  2) if mpio_node else None

        # Extract codes from 13-char puesto code
        dept_reg_code = code[0:4]   # e.g. "0100"
        mpio_reg_code = code[0:7]   # e.g. "0100001"
        zona_code     = code[0:9]   # e.g. "010000101"

        is_exterior = dept_reg_code.startswith("88")

        rows.append({
            "puesto_code":    code,
            "puesto_name":    p["n"],
            "num_mesas":      p["m"],
            "dept_reg_code":  dept_reg_code,
            "dept_name":      dept_node["n"] if dept_node else "",
            "mpio_reg_code_7": mpio_reg_code,
            "mpio_name":      mpio_node["n"] if mpio_node else "",
            "zona_code":      zona_code,
            "zona_name":      zona_node["n"] if zona_node else "",
            "is_exterior":    is_exterior,
        })

    df = pd.DataFrame(rows)

    national = (~df["is_exterior"]).sum()
    exterior = df["is_exterior"].sum()
    print(f"  National puestos: {national:,}")
    print(f"  Exterior puestos: {exterior:,}")
    print(f"  Total:            {len(df):,}")

    df.to_csv(OUT / "puestos_master.csv", index=False)
    print(f"\nSaved → colombia/data/processed/puestos_master.csv")
    print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    parse_nomenclator()
