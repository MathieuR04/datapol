"""
build_data.py — derived data for the "senado limeño" article.

Reads (all outside this folder; nothing here re-scrapes):
  ../erm-2026-candidatos/data/eg2026_candidatos.csv        candidacies (hoja_vida_id join)
  ../erm-2026-candidatos/data/parlamentarios_2026.csv      the 190 elected
  ../erm-2026-candidatos/data/hdv/hdv_eg2026.sqlite        meta.domi_* from the HDVs
  ../../peru/2026eg/metadata/peru_2026_distrito_electoral_roll.csv   padrón by district
  ../../peru/2026eg/metadata/peru_2026_distrito.geojson    district geometries
  ../../peru/2026eg/metadata/peru_2026_departamento.geojson dept geometries
  ../../peru/2026eg/metadata/peru_2026_provincia.geojson   province geometries (Lima split)

Writes (committed; the article reads these statically):
  data/senadores.json           one row per elected senator + domicile + clase
  data/agregados.json           every chart aggregate (waffle, padrón, grupos, …)
  data/lima_met_distritos.geojson   Lima prov + Callao districts (map fig III)
  data/dept_units.geojson       departamentos con Lima Metropolitana como unidad propia,
                                con conteo de senadores/candidatos del distrito nacional

Idempotent — always a full rebuild. Run: python3 scripts/build_data.py
"""

import json
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

HERE   = Path(__file__).parent.parent
ERM    = HERE.parent / "erm-2026-candidatos" / "data"
META26 = HERE.parent.parent / "peru" / "2026eg" / "metadata"
OUT    = HERE / "data"

# APEIM "Lima Moderna" — the standard 12-district segmentation
LIMA_MODERNA = ["SANTIAGO DE SURCO", "MIRAFLORES", "MAGDALENA DEL MAR", "SAN ISIDRO",
                "LA MOLINA", "SAN BORJA", "LINCE", "SAN MIGUEL",
                "BARRANCO", "JESUS MARIA", "PUEBLO LIBRE", "SURQUILLO"]

# domi_dep values that are actually foreign residence (PEX candidates)
EXTERIOR_DEPS = {"AMERICA", "EUROPA", "ASIA", "OCEANIA", "AFRICA", "CHILE"}

# norm(domi_dep) → display name for the departmental map units
DEPT_DISPLAY = {
    "AMAZONAS": "Amazonas", "ANCASH": "Áncash", "APURIMAC": "Apurímac",
    "AREQUIPA": "Arequipa", "AYACUCHO": "Ayacucho", "CAJAMARCA": "Cajamarca",
    "CUSCO": "Cusco", "HUANCAVELICA": "Huancavelica", "HUANUCO": "Huánuco",
    "ICA": "Ica", "JUNIN": "Junín", "LA LIBERTAD": "La Libertad",
    "LAMBAYEQUE": "Lambayeque", "LORETO": "Loreto", "MADRE DE DIOS": "Madre de Dios",
    "MOQUEGUA": "Moquegua", "PASCO": "Pasco", "PIURA": "Piura", "PUNO": "Puno",
    "SAN MARTIN": "San Martín", "TACNA": "Tacna", "TUMBES": "Tumbes",
    "UCAYALI": "Ucayali",
}
CLASES = ["moderna", "lima_met", "interior", "exterior"]


def norm(s):
    if not isinstance(s, str):
        return None
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()


def clase(dep, prov, dist):
    """Domicile class: moderna ⊂ lima_met (prov Lima + Callao) · interior · exterior."""
    if not isinstance(dep, str):        # None/NaN — candidate has no HDV registered
        return None
    if dep in EXTERIOR_DEPS:
        return "exterior"
    if dep == "LIMA" and prov == "LIMA":
        return "moderna" if dist in LIMA_MODERNA else "lima_met"
    if dep == "CALLAO":
        return "lima_met"
    return "interior"


def dep_unit(dep, prov):
    """Domicile → departmental map unit (Lima Metropolitana carved out of dept. Lima)."""
    if not isinstance(dep, str):
        return None
    if dep in EXTERIOR_DEPS:
        return "Exterior"
    if dep == "LIMA":
        return "Lima Metropolitana" if prov == "LIMA" else "Lima Provincias"
    if dep == "CALLAO":
        return "Callao"
    return DEPT_DISPLAY.get(dep, dep.title())


def seat_modality(circ):
    return {"Nacional": "nacional", "Lima": "lima", "Callao": "callao",
            "PEX": "pex"}.get(circ, "departamental")


def cls_counts(df):
    """{n, moderna, lima_met, interior, exterior} for a candidate/senator frame."""
    c = df["clase"].value_counts()
    return {"n": int(len(df)), **{k: int(c.get(k, 0)) for k in CLASES}}


def round_geom(geom, ndigits=3):
    def r(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], ndigits), round(coords[1], ndigits)]
        return [r(c) for c in coords]
    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def build_dept_units(sen, con):
    """Departmental geojson with Lima Metropolitana as its own unit, carrying the
    count of national-district senators and candidates domiciled in each unit."""
    depts = json.loads((META26 / "peru_2026_departamento.geojson").read_text())
    provs = json.loads((META26 / "peru_2026_provincia.geojson").read_text())

    units = {}   # unit name → shapely geometry
    for f in depts["features"]:
        p = f["properties"]
        if p["ubigeo_dept"] == "140000":          # dept. Lima — split below
            continue
        name = "Callao" if p["nombre_dept"] == "EL CALLAO" \
            else DEPT_DISPLAY.get(norm(p["nombre_dept"]), p["nombre_dept"].title())
        units[name] = shape(f["geometry"])
    # split Lima into Metropolitana (prov 140100) + Provincias (the rest)
    lima_met, lima_prov = None, []
    for f in provs["features"]:
        p = f["properties"]
        if p["ubigeo_dept"] != "140000":
            continue
        if p["ubigeo_provincia"] == "140100":
            lima_met = shape(f["geometry"])
        else:
            lima_prov.append(shape(f["geometry"]))
    units["Lima Metropolitana"] = lima_met
    units["Lima Provincias"] = unary_union(lima_prov)

    sen_nac = sen[sen["modalidad"] == "nacional"]
    n_sen = (sen_nac.apply(lambda r: dep_unit(r["domi_dep"], r["domi_prov"]), axis=1)
             .value_counts().to_dict())
    n_can = (con.apply(lambda r: dep_unit(r["domi_dep"], r["domi_prov"]), axis=1)
             .value_counts().to_dict())

    feats = []
    for name, geom in units.items():
        feats.append({
            "type": "Feature",
            "properties": {
                "unit": name,
                "es_lima_met": name == "Lima Metropolitana",
                "senadores": int(n_sen.get(name, 0)),
                "candidatos": int(n_can.get(name, 0)),
            },
            "geometry": round_geom(geom.simplify(0.01, preserve_topology=True)),
        })
    (OUT / "dept_units.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats},
                   ensure_ascii=False, separators=(",", ":")))
    return len(feats), int(n_sen.get("Exterior", 0)), int(n_can.get("Exterior", 0))


def main():
    eg  = pd.read_csv(ERM / "eg2026_candidatos.csv", dtype=str)
    par = pd.read_csv(ERM / "parlamentarios_2026.csv", dtype=str)
    db  = sqlite3.connect(ERM / "hdv" / "hdv_eg2026.sqlite")
    meta = pd.read_sql("SELECT hoja_vida_id, domi_dep, domi_prov, domi_dist "
                       "FROM meta WHERE ok=1", db)
    db.close()
    meta["hoja_vida_id"] = meta["hoja_vida_id"].astype(str)

    # ── senators: dni → domicile via any candidacy's hoja_vida_id ────────────
    hv = eg[eg["hoja_vida_id"] != "0"][["dni", "hoja_vida_id"]].drop_duplicates("dni")
    sen = (par[par["cargo"] == "senador"]
           .merge(hv, on="dni", how="left")
           .merge(meta, on="hoja_vida_id", how="left"))
    sen["modalidad"] = sen["circunscripcion"].map(seat_modality)
    sen["clase"] = [clase(d, p, di) for d, p, di in
                    zip(sen["domi_dep"], sen["domi_prov"], sen["domi_dist"])]

    # departamental: lives in the department they represent?
    def en_su_dep(r):
        if r["modalidad"] != "departamental":
            return None
        c = norm(r["circunscripcion"])
        if c == "LIMA PROVINCIAS":
            return bool(r["domi_dep"] == "LIMA" and r["domi_prov"] != "LIMA")
        return bool(c == r["domi_dep"])
    sen["en_su_dep"] = sen.apply(en_su_dep, axis=1)

    senadores = sen[["name", "partido", "circunscripcion", "modalidad", "votes",
                     "domi_dep", "domi_prov", "domi_dist", "clase", "en_su_dep"]]
    senadores.to_json(OUT / "senadores.json", orient="records", force_ascii=False)

    # ── national-district candidates (listas INSCRITAS, con HDV) ─────────────
    uni = (eg[(eg["tipo_eleccion_id"] == "20") & (eg["estado_lista"] == "INSCRITO")]
           .merge(meta, on="hoja_vida_id", how="left"))
    uni["clase"] = [clase(d, p, di) for d, p, di in
                    zip(uni["domi_dep"], uni["domi_prov"], uni["domi_dist"])]
    uni["posicion"] = uni["posicion"].astype(int)
    con = uni[uni["clase"].notna()].copy()

    # three groupings for the horizontal bars: cabeza de lista (#1), top-5, todos
    grupos = {
        "cabeza": cls_counts(con[con["posicion"] == 1]),
        "top5":   cls_counts(con[con["posicion"] <= 5]),
        "todos":  cls_counts(con),
    }

    # ── padrón shares ────────────────────────────────────────────────────────
    roll = pd.read_csv(META26 / "peru_2026_distrito_electoral_roll.csv")
    roll["dist_norm"] = roll["nombre_distrito"].map(norm)
    padron_total = int(roll["num_electores"].sum())
    mask_limamet = (roll["ubigeo_provincia"] == 140100) | (roll["nombre_dept"] == "CALLAO")
    mask_moderna = (roll["ubigeo_provincia"] == 140100) & roll["dist_norm"].isin(LIMA_MODERNA)
    padron_limamet = int(roll.loc[mask_limamet, "num_electores"].sum())
    padron_moderna = int(roll.loc[mask_moderna, "num_electores"].sum())

    # ── senator count per domicile district (Lima-Met map + table) ───────────
    por_distrito = (sen.dropna(subset=["domi_dist"])
                    .groupby(["domi_dep", "domi_prov", "domi_dist"]).size()
                    .reset_index(name="senadores")
                    .sort_values("senadores", ascending=False))

    # ── departmental map (Lima Metropolitana carved out) ─────────────────────
    n_units, ext_sen, ext_can = build_dept_units(sen, con)

    agregados = {
        "definicion_lima_moderna": LIMA_MODERNA,
        "padron": {"total": padron_total, "lima_met": padron_limamet,
                   "lima_moderna": padron_moderna},
        "senado": {
            "total": cls_counts(sen),
            "por_modalidad": {m: cls_counts(g) for m, g in sen.groupby("modalidad")},
            "departamental_en_su_dep": int(sen["en_su_dep"].sum()),
            "departamental_n": int((sen["modalidad"] == "departamental").sum()),
            "por_distrito": por_distrito.to_dict(orient="records"),
        },
        "candidatos_nacional": {
            "inscritos": int(len(uni)),
            "con_hdv": int(len(con)),
            "sin_hdv": int(uni["clase"].isna().sum()),
            "total": cls_counts(con),
            "grupos": grupos,
        },
        "mapa_dept_exterior": {"senadores": ext_sen, "candidatos": ext_can},
    }
    (OUT / "agregados.json").write_text(
        json.dumps(agregados, ensure_ascii=False, indent=1))

    # ── map: Lima province + Callao districts only, rounded coords ───────────
    gj = json.loads((META26 / "peru_2026_distrito.geojson").read_text())
    sen_dist = {(r["domi_dep"], r["domi_dist"]): int(r["senadores"])
                for _, r in por_distrito.iterrows()}
    elect = {str(r["ubigeo_distrito"]).zfill(6): int(r["num_electores"])
             for _, r in roll.iterrows()}

    def rnd(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], 4), round(coords[1], 4)]
        return [rnd(c) for c in coords]

    feats = []
    for f in gj["features"]:
        p = f["properties"]
        if p["ubigeo_provincia"] != "140100" and p["nombre_dept"] != "CALLAO":
            continue
        dist = norm(p["nombre_distrito"])
        dep = "CALLAO" if p["nombre_dept"] == "CALLAO" else "LIMA"
        feats.append({
            "type": "Feature",
            "properties": {
                "distrito": p["nombre_distrito"],
                "dep": dep,
                "moderna": dist in LIMA_MODERNA,
                "senadores": sen_dist.get((dep, dist), 0),
                "electores": elect.get(p["ubigeo_distrito"], 0),
            },
            "geometry": {"type": f["geometry"]["type"],
                         "coordinates": rnd(f["geometry"]["coordinates"])},
        })
    (OUT / "lima_met_distritos.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats},
                   ensure_ascii=False, separators=(",", ":")))

    print(f"senadores.json: {len(senadores)} · agregados.json · "
          f"lima_met_distritos.geojson: {len(feats)} distritos · "
          f"dept_units.geojson: {n_units} unidades "
          f"({(OUT/'dept_units.geojson').stat().st_size/1e3:.0f} KB)")
    print("senado:", agregados["senado"]["total"])
    print("grupos:", grupos)


if __name__ == "__main__":
    main()
