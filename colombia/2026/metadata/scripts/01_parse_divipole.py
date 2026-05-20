"""
01_parse_divipole.py
Parse Divipole PDF into a clean CSV — all puestos, national + exterior.
Output: colombia/data/processed/divipole.csv
"""

import pdfplumber
import pandas as pd
from pathlib import Path

RAW = Path(__file__).parent.parent / "data" / "raw"
OUT = Path(__file__).parent.parent / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

PDF_PATH = RAW / "Divipole_definitiva_ Elecciones_Congreso_2026_GEO_CITREP_Exterior_L_V_v5.pdf"

# Exact column positions from Row 5 of page 1
# [dd, mm, zz, pp, departamento, municipio, puesto, comuna, dirección,
#  mujeres, hombres, total, mesas_domingo, Latitud, Longitud,
#  CITREP, mesas_lun_jue_ext, mesas_vie_ext, mesas_sab_ext,
#  mujeres_ext, hombres_ext, total_censo_adscrito, agrupados_lun_sab]
COL_NAMES = [
    "dept_reg", "mpio_reg", "zona", "puesto_num",
    "dept_name", "mpio_name", "puesto_name", "comuna", "direccion",
    "censo_mujeres", "censo_hombres", "censo_total",
    "num_mesas",
    "latitud", "longitud",
    "citrep",
    "mesas_ext_lun_jue", "mesas_ext_vie", "mesas_ext_sab",
    "censo_mujeres_ext", "censo_hombres_ext", "censo_total_ext",
    "agrupados_ext",
]
N_COLS = len(COL_NAMES)  # 23


def is_header_row(row):
    text = " ".join(str(c) for c in row if c).lower()
    return any(kw in text for kw in [
        "código de divipole", "división política", "coordinación",
        "georeferenciación", "exterior lunes", "proceso", "formato",
        "aprobado", "fecha de corte", "departamento", "municipio",
        "dd", "mujeres", "hombres",
    ])


def is_total_row(row):
    first = str(row[0] or "").strip()
    return first.upper().startswith("TOTAL")


def clean_int(val):
    if val is None:
        return None
    s = str(val).replace(".", "").replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def clean_float(val):
    if val is None:
        return None
    s = str(val).replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_divipole():
    rows = []
    print(f"Opening {PDF_PATH.name} …")

    with pdfplumber.open(PDF_PATH) as pdf:
        total = len(pdf.pages)
        print(f"  {total} pages")

        for page_num, page in enumerate(pdf.pages, 1):
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
                "join_tolerance": 3,
            })
            if not table:
                continue

            for row in table:
                if is_header_row(row) or is_total_row(row):
                    continue

                # Must start with a 2-digit dept code
                first = str(row[0] or "").strip()
                if not first.isdigit() or len(first) > 2:
                    continue

                # Pad row to expected width
                padded = list(row) + [None] * (N_COLS - len(row))
                padded = padded[:N_COLS]

                record = {}
                for i, col in enumerate(COL_NAMES):
                    record[col] = str(padded[i]).strip() if padded[i] is not None else ""

                rows.append(record)

            if page_num % 50 == 0:
                print(f"  … page {page_num}/{total}, rows: {len(rows)}")

    print(f"\nRaw rows extracted: {len(rows)}")
    df = pd.DataFrame(rows)

    # Clean code columns
    df["dept_reg"] = df["dept_reg"].str.zfill(2)
    df["mpio_reg"] = df["mpio_reg"].str.zfill(3)
    df["zona"]     = df["zona"].str.zfill(2)
    df["puesto_num"] = df["puesto_num"].str.zfill(2)

    # Build 13-char puesto code matching nomenclator 'c' field:
    # dept_reg(2) + "00" + mpio_reg(3) + zona(2) + "00" + puesto_num(2)
    df["puesto_code"] = (
        df["dept_reg"] + "00" + df["mpio_reg"] + df["zona"] + "00" + df["puesto_num"]
    )

    # is_exterior flag
    df["is_exterior"] = df["dept_reg"] == "88"

    # Clean numeric columns
    for col in ["censo_mujeres", "censo_hombres", "censo_total", "num_mesas",
                "mesas_ext_lun_jue", "mesas_ext_vie", "mesas_ext_sab",
                "censo_mujeres_ext", "censo_hombres_ext", "censo_total_ext"]:
        df[col] = df[col].apply(clean_int)

    for col in ["latitud", "longitud"]:
        df[col] = df[col].apply(clean_float)

    # Drop grand total row (catches any straggler)
    df = df[df["dept_reg"] != "00"].reset_index(drop=True)

    # Reorder: puesto_code first
    cols_ordered = ["puesto_code", "is_exterior"] + COL_NAMES
    df = df[[c for c in cols_ordered if c in df.columns]]

    df.to_csv(OUT / "divipole.csv", index=False)

    n_national = (~df["is_exterior"]).sum()
    n_ext = df["is_exterior"].sum()
    print(f"\nSaved {len(df)} rows → divipole.csv")
    print(f"  National: {n_national:,}  |  Exterior: {n_ext:,}")
    print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    parse_divipole()
