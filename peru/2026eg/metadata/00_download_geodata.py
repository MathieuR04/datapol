"""
00_download_geodata.py — Peru 2026 metadata setup

Downloads all district-level GeoJSON polygons from ONPE's amcharts data layer
and produces three unified GeoJSON files (national territory only):

  peru_2026_distrito.geojson      ← 1891 districts with geometry
  peru_2026_provincia.geojson     ← 196 provinces (dissolved from districts)
  peru_2026_departamento.geojson  ← 25 departments (dissolved from districts)

Also produces the full electoral roll (national + exterior):
  peru_2026_distrito_electoral_roll.csv

Electoral roll includes:
  • 1892 national districts (1891 with geometry + 3 without: Kumpirushiato,
    Alto Trujillo, San Antonio — exist in ONPE API but not in amcharts layer)
  • 210 exterior districts (5 continents → 77 countries → 210 cities)
    with is_exterior=True; no geometry available

num_mesas and num_electores are placeholder zeros. Populate from:
  - num_mesas:    actas_total per district in results CSV (once scraped via 02a)
  - num_electores: ONPE official padron electoral (published separately)

Source map server:
  https://resultadoelectoral.onpe.gob.pe/assets/lib/amcharts5/geodata/json/
Source ubigeos API:
  https://resultadoelectoral.onpe.gob.pe/presentacion-backend/ubigeos/

Usage:
  pip install geopandas shapely
  python3 metadata/00_download_geodata.py
"""

import json
import ssl
import time
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.validation import make_valid

# ONPE uses a self-signed certificate chain — skip verification
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

# ── Config ─────────────────────────────────────────────────────────────────────

GEO_BASE = "https://resultadoelectoral.onpe.gob.pe/assets/lib/amcharts5/geodata/json"
API_BASE = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend"

GEO_HEADERS = {
    "Referer":        "https://resultadoelectoral.onpe.gob.pe/main/presidenciales",
    "User-Agent":     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept":         "application/json, */*;q=0.1",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-fetch-dest": "empty",
}

API_HEADERS = {
    "Referer":        "https://resultadoelectoral.onpe.gob.pe/main/presidenciales",
    "User-Agent":     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept":         "application/json, */*;q=0.1",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-fetch-dest": "empty",
}

METADATA = Path(__file__).parent
ID_ELECCION = 10

# 25 department amcharts IDs (from peruLow.json, excluding PE-LKT Lago Titicaca)
DEPT_IDS = [
    "010000",  # Amazonas
    "020000",  # Áncash
    "030000",  # Apurímac
    "040000",  # Arequipa
    "050000",  # Ayacucho
    "060000",  # Cajamarca
    "240000",  # El Callao
    "070000",  # Cusco
    "080000",  # Huancavelica
    "090000",  # Huánuco
    "100000",  # Ica
    "110000",  # Junín
    "120000",  # La Libertad
    "130000",  # Lambayeque
    "140000",  # Lima
    "150000",  # Loreto
    "160000",  # Madre de Dios
    "170000",  # Moquegua
    "180000",  # Pasco
    "190000",  # Piura
    "200000",  # Puno
    "210000",  # San Martín
    "220000",  # Tacna
    "230000",  # Tumbes
    "250000",  # Ucayali
]

# Districts that exist in the ONPE electoral API but lack polygon in amcharts
MISSING_NATIONAL = [
    {"ubigeo_distrito": "070916", "ubigeo_provincia": "070900", "ubigeo_dept": "070000",
     "nombre_distrito": "KUMPIRUSHIATO", "nombre_provincia": "LA CONVENCIÓN", "nombre_dept": "CUSCO"},
    {"ubigeo_distrito": "120113", "ubigeo_provincia": "120100", "ubigeo_dept": "120000",
     "nombre_distrito": "ALTO TRUJILLO",  "nombre_provincia": "TRUJILLO",        "nombre_dept": "LA LIBERTAD"},
    {"ubigeo_distrito": "170107", "ubigeo_provincia": "170100", "ubigeo_dept": "170000",
     "nombre_distrito": "SAN ANTONIO",    "nombre_provincia": "MARISCAL NIETO",  "nombre_dept": "MOQUEGUA"},
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def fetch_geo_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=GEO_HEADERS)
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def fetch_api_json(path: str) -> list:
    url = API_BASE + path
    req = urllib.request.Request(url, headers=API_HEADERS)
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read()).get("data", [])


# ── National GeoJSON ───────────────────────────────────────────────────────────

def build_district_geojson() -> gpd.GeoDataFrame:
    """Download all national district GeoJSONs and merge into one GeoDataFrame."""
    all_features = []
    total_depts  = len(DEPT_IDS)

    for i, dept_id in enumerate(DEPT_IDS, 1):
        print(f"  [{i:2d}/{total_depts}] Dept {dept_id} …", end=" ", flush=True)
        try:
            prov_features = fetch_geo_json(f"{GEO_BASE}/departamentos/{dept_id}.json").get("features", [])
        except Exception as e:
            print(f"ERROR (dept): {e}")
            continue

        prov_ids   = [f["properties"]["ID"] for f in prov_features]
        dist_count = 0

        for prov_id in prov_ids:
            try:
                dist_features = fetch_geo_json(f"{GEO_BASE}/provincias/{prov_id}.json").get("features", [])
                for feat in dist_features:
                    p = feat.get("properties", {})
                    feat["properties"] = {
                        "ubigeo_distrito":  str(p.get("ID", "")),
                        "ubigeo_provincia": str(p.get("ID", ""))[:4] + "00",
                        "ubigeo_dept":      str(p.get("ID", ""))[:2] + "0000",
                        "nombre_distrito":  p.get("DISTRITO", p.get("name", "")),
                        "nombre_provincia": p.get("PROVINCIA", ""),
                        "nombre_dept":      p.get("DEPARTAMEN", ""),
                    }
                    all_features.append(feat)
                dist_count += len(dist_features)
                time.sleep(0.05)
            except Exception as e:
                print(f"\n    WARN province {prov_id}: {e}", end="")

        print(f"{len(prov_ids)} provinces, {dist_count} districts")
        time.sleep(0.1)

    print(f"\nTotal national districts with geometry: {len(all_features)}")

    fc  = {"type": "FeatureCollection", "features": all_features}
    gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        print(f"  Fixing {invalid.sum()} invalid geometries …")
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].apply(make_valid)

    gdf = gdf.set_index("ubigeo_distrito", drop=False)
    return gdf


def dissolve_provincia(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return (
        gdf.dissolve(by="ubigeo_provincia")
           .reset_index()
           [["ubigeo_provincia", "ubigeo_dept", "nombre_provincia", "nombre_dept", "geometry"]]
    )


def dissolve_dept(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return (
        gdf.dissolve(by="ubigeo_dept")
           .reset_index()
           [["ubigeo_dept", "nombre_dept", "geometry"]]
    )


# ── Exterior districts (from ONPE ubigeos API) ────────────────────────────────

def download_exterior_districts() -> list[dict]:
    """
    Download exterior circumscription hierarchy via ONPE's ubigeos API.
    Structure: continent (dept) → country (provincia) → city (distrito)
    Ubigeo codes: 910000=África, 920000=América, 930000=Asia, 940000=Europa, 950000=Oceanía
    """
    print("Fetching exterior hierarchy from ONPE ubigeos API …")
    rows = []

    continents = fetch_api_json(f"/ubigeos/departamentos?idEleccion={ID_ELECCION}&idAmbitoGeografico=2")
    print(f"  Continents: {len(continents)}")

    for cont in continents:
        cont_ubigeo = cont["ubigeo"]
        cont_nombre = cont["nombre"]

        countries = fetch_api_json(
            f"/ubigeos/provincias?idEleccion={ID_ELECCION}&idAmbitoGeografico=2"
            f"&idUbigeoDepartamento={cont_ubigeo}"
        )
        time.sleep(0.05)

        for country in countries:
            ctry_ubigeo = country["ubigeo"]
            ctry_nombre = country["nombre"]

            cities = fetch_api_json(
                f"/ubigeos/distritos?idEleccion={ID_ELECCION}&idAmbitoGeografico=2"
                f"&idUbigeoProvincia={ctry_ubigeo}"
            )
            time.sleep(0.03)

            for city in cities:
                rows.append({
                    "ubigeo_distrito":  city["ubigeo"],
                    "ubigeo_provincia": ctry_ubigeo,
                    "ubigeo_dept":      cont_ubigeo,
                    "nombre_distrito":  city["nombre"],
                    "nombre_provincia": ctry_nombre,
                    "nombre_dept":      cont_nombre,
                    "is_exterior":      True,
                    "has_geometry":     False,
                })

        print(f"    {cont_nombre}: {len(countries)} countries")

    print(f"  Total exterior districts: {len(rows)}")
    return rows


# ── Electoral roll ─────────────────────────────────────────────────────────────

def write_electoral_roll(gdf: gpd.GeoDataFrame, exterior: list[dict]) -> None:
    """
    Write combined electoral roll (national + exterior).

    num_mesas:    populate from actas_total in district results CSV (02a output)
    num_electores: populate from ONPE's official padron electoral (separate download)
    """
    path = METADATA / "peru_2026_distrito_electoral_roll.csv"

    # National rows from GeoDataFrame
    nat = gdf[["ubigeo_distrito", "ubigeo_provincia", "ubigeo_dept",
               "nombre_distrito", "nombre_provincia", "nombre_dept"]].copy()
    nat = nat.sort_values("ubigeo_distrito").drop_duplicates("ubigeo_distrito")
    nat["is_exterior"]  = False
    nat["has_geometry"] = True

    # 3 missing national districts (in ONPE API, not in amcharts cartography)
    missing_rows = []
    existing_ubigeos = set(nat["ubigeo_distrito"])
    for d in MISSING_NATIONAL:
        if d["ubigeo_distrito"] not in existing_ubigeos:
            missing_rows.append({**d, "is_exterior": False, "has_geometry": False})

    # Exterior rows
    ext = pd.DataFrame(exterior)

    combined = pd.concat([nat, pd.DataFrame(missing_rows), ext], ignore_index=True)
    combined["num_mesas"]     = 0
    combined["num_electores"] = 0
    combined = combined.sort_values(["is_exterior", "ubigeo_distrito"])

    combined.to_csv(path, index=False)

    n_nat = len(combined[~combined["is_exterior"]])
    n_ext = len(combined[combined["is_exterior"]])
    print(f"  Electoral roll → {path.name}")
    print(f"    {n_nat} national districts ({len(missing_rows)} without geometry)")
    print(f"    {n_ext} exterior districts (no geometry)")
    print(f"    {len(combined)} total")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=== Peru 2026 — GeoJSON + Electoral Roll ===\n")

    print("Downloading national district polygons …")
    gdf_dist = build_district_geojson()

    print("\nDissolving → provincia …")
    gdf_prov = dissolve_provincia(gdf_dist)
    print(f"  {len(gdf_prov)} provinces")

    print("Dissolving → departamento …")
    gdf_dept = dissolve_dept(gdf_dist)
    print(f"  {len(gdf_dept)} departments")

    print("\nWriting GeoJSONs (national territory only) …")
    out_dist = METADATA / "peru_2026_distrito.geojson"
    out_prov = METADATA / "peru_2026_provincia.geojson"
    out_dept = METADATA / "peru_2026_departamento.geojson"

    gdf_dist.reset_index(drop=True).to_file(out_dist, driver="GeoJSON")
    gdf_prov.to_file(out_prov, driver="GeoJSON")
    gdf_dept.to_file(out_dept, driver="GeoJSON")

    print(f"  distrito     → {out_dist.name}  ({len(gdf_dist)} features)")
    print(f"  provincia    → {out_prov.name}  ({len(gdf_prov)} features)")
    print(f"  departamento → {out_dept.name}  ({len(gdf_dept)} features)")

    print("\nDownloading exterior district hierarchy …")
    exterior = download_exterior_districts()

    print("\nWriting electoral roll (national + exterior) …")
    write_electoral_roll(gdf_dist.reset_index(drop=True), exterior)

    print("\nDone.")


if __name__ == "__main__":
    main()
