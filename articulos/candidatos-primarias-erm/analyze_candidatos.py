"""
Analysis of primary election candidates.
Run after scrape_candidatos.py has produced candidatos.xlsx.
Produces: analysis_candidatos.xlsx with multiple sheets.
"""

import pandas as pd

INPUT  = "candidatos.xlsx"
OUTPUT = "analysis_candidatos.xlsx"

# ── Load & filter ────────────────────────────────────────────────────────────

df = pd.read_excel(INPUT)

CARGOS = ["GOBERNADOR", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
df = df[df["CARGO"].isin(CARGOS)].copy()

# Unique key columns per cargo type
df["GEO_GOB"]  = df["REGION"]
df["GEO_PROV"] = df["REGION"] + " | " + df["PROVINCIA"]
df["GEO_DIST"] = df["REGION"] + " | " + df["PROVINCIA"] + " | " + df["DISTRITO"]

# ── Part A: candidates per party ─────────────────────────────────────────────
# Distinct (presentacion, geo) per cargo → count of geos per party

def party_coverage(cargo, geo_col):
    sub = df[df["CARGO"] == cargo][["PRESENTACION", geo_col]].drop_duplicates()
    return (sub.groupby("PRESENTACION")[geo_col]
               .nunique()
               .reset_index()
               .rename(columns={geo_col: "N_LUGARES"})
               .sort_values("N_LUGARES", ascending=False))

gob_party  = party_coverage("GOBERNADOR",        "GEO_GOB")
prov_party = party_coverage("ALCALDE PROVINCIAL", "GEO_PROV")
dist_party = party_coverage("ALCALDE DISTRITAL",  "GEO_DIST")

gob_party.columns  = ["PRESENTACION", "N_REGIONES_GOB"]
prov_party.columns = ["PRESENTACION", "N_PROVINCIAS_ALCALDE_PROV"]
dist_party.columns = ["PRESENTACION", "N_DISTRITOS_ALCALDE_DIST"]

part_a = (gob_party
          .merge(prov_party, on="PRESENTACION", how="outer")
          .merge(dist_party, on="PRESENTACION", how="outer")
          .fillna(0)
          .astype({"N_REGIONES_GOB": int,
                   "N_PROVINCIAS_ALCALDE_PROV": int,
                   "N_DISTRITOS_ALCALDE_DIST": int})
          .sort_values("N_DISTRITOS_ALCALDE_DIST", ascending=False))

# ── Part B: parties competing per geography ──────────────────────────────────

def competition_distribution(cargo, geo_col, geo_label):
    """How many geos have exactly N parties competing?"""
    sub = df[df["CARGO"] == cargo][["PRESENTACION", geo_col]].drop_duplicates()
    parties_per_geo = (sub.groupby(geo_col)["PRESENTACION"]
                          .nunique()
                          .reset_index()
                          .rename(columns={"PRESENTACION": "N_PARTIDOS",
                                           geo_col: geo_label}))
    dist_tbl = (parties_per_geo.groupby("N_PARTIDOS")[geo_label]
                               .count()
                               .reset_index()
                               .rename(columns={geo_label: "N_LUGARES"})
                               .sort_values("N_PARTIDOS"))
    return parties_per_geo, dist_tbl

gob_geo,  gob_dist  = competition_distribution("GOBERNADOR",        "GEO_GOB",  "REGION")
prov_geo, prov_dist = competition_distribution("ALCALDE PROVINCIAL", "GEO_PROV", "REGION_PROVINCIA")
dist_geo, dist_dist = competition_distribution("ALCALDE DISTRITAL",  "GEO_DIST", "REGION_PROVINCIA_DISTRITO")

# Label the distribution tables
gob_dist.columns  = ["N_PARTIDOS_COMPITIENDO", "N_REGIONES"]
prov_dist.columns = ["N_PARTIDOS_COMPITIENDO", "N_PROVINCIAS"]
dist_dist.columns = ["N_PARTIDOS_COMPITIENDO", "N_DISTRITOS"]

# Extremes: top & bottom N places by number of competing parties
def extremes(parties_per_geo, geo_col, n=10):
    s = parties_per_geo.sort_values("N_PARTIDOS", ascending=False)
    top    = s.head(n).reset_index(drop=True)
    bottom = s.tail(n).sort_values("N_PARTIDOS").reset_index(drop=True)
    return top, bottom

gob_top,  gob_bot  = extremes(gob_geo,  "REGION",                    n=5)
prov_top, prov_bot = extremes(prov_geo, "REGION_PROVINCIA",           n=10)
dist_top, dist_bot = extremes(dist_geo, "REGION_PROVINCIA_DISTRITO",  n=10)

# ── Print summary ────────────────────────────────────────────────────────────

print("=" * 60)
print("PART A — Coverage per party")
print("=" * 60)
print(part_a.to_string(index=False))

print("\n" + "=" * 60)
print("PART B — Distribution of competition (GOBERNADOR)")
print("=" * 60)
print(gob_dist.to_string(index=False))
print("\nMost contested regions:")
print(gob_top.to_string(index=False))
print("\nLeast contested regions:")
print(gob_bot.to_string(index=False))

print("\n" + "=" * 60)
print("PART B — Distribution of competition (ALCALDE PROVINCIAL)")
print("=" * 60)
print(prov_dist.to_string(index=False))
print("\nMost contested provinces:")
print(prov_top.to_string(index=False))
print("\nLeast contested provinces:")
print(prov_bot.to_string(index=False))

print("\n" + "=" * 60)
print("PART B — Distribution of competition (ALCALDE DISTRITAL)")
print("=" * 60)
print(dist_dist.to_string(index=False))
print("\nMost contested districts:")
print(dist_top.to_string(index=False))
print("\nLeast contested districts:")
print(dist_bot.to_string(index=False))

# ── Save to Excel ────────────────────────────────────────────────────────────

with pd.ExcelWriter(OUTPUT, engine="openpyxl") as writer:
    part_a.to_excel(writer,     sheet_name="A_cobertura_por_partido", index=False)
    gob_dist.to_excel(writer,   sheet_name="B_dist_gobernador",       index=False)
    gob_geo.to_excel(writer,    sheet_name="B_detalle_gobernador",    index=False)
    prov_dist.to_excel(writer,  sheet_name="B_dist_alc_provincial",   index=False)
    prov_geo.to_excel(writer,   sheet_name="B_detalle_alc_provincial",index=False)
    dist_dist.to_excel(writer,  sheet_name="B_dist_alc_distrital",    index=False)
    dist_geo.to_excel(writer,   sheet_name="B_detalle_alc_distrital", index=False)

print(f"\n✓ Saved to {OUTPUT}")
