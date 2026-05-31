"""
Scraper for Peru electoral candidate PDFs.
Handles sections: GOBERNADOR Y VICEGOBERNADOR, CONSEJERO REGIONAL,
MUNICIPAL PROVINCIAL, MUNICIPAL DISTRITAL.
"""

import re
import sys
import glob
from pathlib import Path
import pandas as pd

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

AMBITO_PATTERNS = [
    "GOBERNADOR Y VICEGOBERNADOR",
    "CONSEJERO REGIONAL",
    "MUNICIPAL PROVINCIAL",
    "MUNICIPAL DISTRITAL",
]

# Metadata label → column name
META_LABELS = {
    "Presentación": "PRESENTACION",
    "Región": "REGION",
    "Provincia": "PROVINCIA",
    "Distrito": "DISTRITO",
    "Modalidad": "MODALIDAD",
}

# Header lines that mark where data rows start (we skip them)
HEADER_ROW_RE = re.compile(
    r"N[°º]\s*DE\s*(FÓRMULA|FORMULA|LISTA)\s+",
    re.IGNORECASE,
)

# A data row: starts with an integer (N° de fórmula/lista)
DATA_ROW_RE = re.compile(
    r"^\s*(\d+)"          # col1 : N° fórmula or lista
    r"\s+"
    r"(\d*)"              # col2 : ORDEN (may be empty for REEMPLAZANTEs)
    r"\s{2,}"             # separator (at least 2 spaces to avoid catching single-digit names)
    r"(.+?)"              # NOMBRES Y APELLIDOS
    r"\s{2,}"             # separator
    r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ ]+)\s*$"  # CARGO
)

# Alternative: row that has only N°lista + name + cargo (REEMPLAZANTE rows with no ORDEN)
DATA_ROW_NO_ORDEN_RE = re.compile(
    r"^\s*(\d+)"          # N° lista
    r"\s{3,}"             # big gap (no orden column)
    r"(.+?)"              # NOMBRES Y APELLIDOS
    r"\s{2,}"
    r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ ]+)\s*$"
)

PAGE_RE = re.compile(r"^\s*[Pp]ágina\s+\d+\s*$")
SECTION_TITLE_RE = re.compile(r"^\s*(Datos generales|La información|Nombre de|Tipo de|Fecha de)\s")


def is_ambito_line(line: str) -> str | None:
    """Return the ambito name if this line is a section title, else None."""
    stripped = line.strip().rstrip(".")
    for pattern in AMBITO_PATTERNS:
        if stripped.upper() == pattern:
            return pattern
    return None


def parse_meta_line(line: str) -> tuple[str, str] | None:
    """If line is 'Label   Value', return (col_name, value)."""
    for label, col in META_LABELS.items():
        if line.strip().startswith(label):
            value = line.strip()[len(label):].strip()
            if value:
                return col, value
    return None


def parse_data_row(line: str) -> dict | None:
    """Try to parse a candidate data row. Returns dict or None."""
    # Skip page numbers, headers, empty lines
    if not line.strip():
        return None
    if PAGE_RE.match(line):
        return None
    if HEADER_ROW_RE.search(line):
        return None
    if SECTION_TITLE_RE.match(line):
        return None

    m = DATA_ROW_RE.match(line)
    if m:
        return {
            "_num": m.group(1).strip(),
            "_orden": m.group(2).strip(),
            "NOMBRES Y APELLIDOS": m.group(3).strip(),
            "CARGO": m.group(4).strip(),
        }

    # Try the no-orden variant (REEMPLAZANTE rows)
    m2 = DATA_ROW_NO_ORDEN_RE.match(line)
    if m2:
        return {
            "_num": m2.group(1).strip(),
            "_orden": "",
            "NOMBRES Y APELLIDOS": m2.group(2).strip(),
            "CARGO": m2.group(3).strip(),
        }

    return None


def scrape_pdf(pdf_path: str) -> list[dict]:
    """Extract all candidate rows from a single PDF."""
    import subprocess

    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True, encoding="utf-8"
    )
    raw_text = result.stdout

    rows = []
    current_ambito = None
    current_meta = {
        "PRESENTACION": "",
        "REGION": "",
        "PROVINCIA": "",
        "DISTRITO": "",
        "MODALIDAD": "",
    }
    # Track which num column is "formula" vs "lista"
    current_num_type = None   # "FORMULA" or "LISTA"

    for line in raw_text.splitlines():
        # Detect ambito section header
        ambito = is_ambito_line(line)
        if ambito:
            current_ambito = ambito
            # Reset geography fields for new section
            current_meta = {k: "" for k in current_meta}
            continue

        if current_ambito is None:
            continue

        # Detect header row to know if num col is formula or lista
        hm = HEADER_ROW_RE.search(line)
        if hm:
            current_num_type = "LISTA" if "LISTA" in line.upper() else "FORMULA"
            continue

        # Detect metadata lines
        meta = parse_meta_line(line)
        if meta:
            col, val = meta
            current_meta[col] = val
            # Reset lower-level geography when higher-level changes
            if col == "REGION":
                current_meta["PROVINCIA"] = ""
                current_meta["DISTRITO"] = ""
            elif col == "PROVINCIA":
                current_meta["DISTRITO"] = ""
            continue

        # Try to parse data row
        row = parse_data_row(line)
        if row:
            num_val = row["_num"]
            orden_val = row["_orden"]

            record = {
                "AMBITO": current_ambito,
                "PRESENTACION": current_meta["PRESENTACION"],
                "REGION": current_meta["REGION"],
                "PROVINCIA": current_meta["PROVINCIA"],
                "DISTRITO": current_meta["DISTRITO"],
                "MODALIDAD": current_meta["MODALIDAD"],
                "N DE FORMULA": num_val if current_num_type == "FORMULA" else "",
                "N DE LISTA": num_val if current_num_type == "LISTA" else "",
                "ORDEN": orden_val,
                "NOMBRES Y APELLIDOS": row["NOMBRES Y APELLIDOS"],
                "CARGO": row["CARGO"],
            }
            rows.append(record)

    return rows


def main(pdf_paths: list[str], output_path: str):
    all_rows = []
    for path in pdf_paths:
        print(f"  Processing: {path}")
        rows = scrape_pdf(path)
        print(f"    → {len(rows)} rows extracted")
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows, columns=[
        "AMBITO", "PRESENTACION", "REGION", "PROVINCIA", "DISTRITO",
        "MODALIDAD", "N DE FORMULA", "N DE LISTA", "ORDEN",
        "NOMBRES Y APELLIDOS", "CARGO"
    ])

    # Save to Excel
    df.to_excel(output_path, index=False)
    print(f"\n✓ Saved {len(df)} rows to {output_path}")
    print(df.head(10).to_string())
    return df


if __name__ == "__main__":
    pdfs = sys.argv[1:] if len(sys.argv) > 1 else [
        "/mnt/user-data/uploads/8111093-partido-politico-juntos-por-el-peru-nacional.pdf"
    ]
    out = "candidatos.xlsx"
    main(pdfs, out)
