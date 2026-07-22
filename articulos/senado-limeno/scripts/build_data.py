"""
build_data.py — derived data for the "senado limeño" article.

Reads (all outside this folder; nothing here re-scrapes):
  ../erm-2026-candidatos/data/eg2026_candidatos.csv        candidacies (hoja_vida_id join)
  ../erm-2026-candidatos/data/parlamentarios_2026.csv      the 190 elected
  ../erm-2026-candidatos/data/hdv/hdv_eg2026.sqlite        meta.domi_* from the HDVs
  ../../peru/2026eg/metadata/peru_2026_distrito_electoral_roll.csv   padrón by district
  ../../peru/2026eg/metadata/peru_2026_distrito.geojson    district geometries

Writes (committed; the article reads these statically):
  data/senadores.json           one row per elected senator + domicile + clase
  data/agregados.json           every chart aggregate (waffle, padrón, posiciones, …)
  data/lima_met_distritos.geojson   Lima prov + Callao only, coords rounded, with
                                    lima_moderna flag + senator count + electores

Idempotent — always a full rebuild. Run: python3 scripts/build_data.py
"""

import json
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

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


def norm(s):
    if not isinstance(s, str):
        return None
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()


def clase(dep, prov, dist):
    """Domicile class: moderna ⊂ lima_met (prov Lima + Callao) · pais · exterior."""
    if not isinstance(dep, str):        # None/NaN — candidate has no HDV registered
        return None
    if dep in EXTERIOR_DEPS:
        return "exterior"
    if dep == "LIMA" and prov == "LIMA":
        return "moderna" if dist in LIMA_MODERNA else "lima_met"
    if dep == "CALLAO":
        return "lima_met"
    return "pais"


def seat_modality(circ):
    return {"Nacional": "nacional", "Lima": "lima", "Callao": "callao",
            "PEX": "pex"}.get(circ, "departamental")


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
    con = uni[uni["clase"].notna()]

    # Lima-Met / Moderna share by list position (1–30)
    por_pos = []
    for pos, g in con.groupby("posicion"):
        por_pos.append({"pos": int(pos), "n": len(g),
                        "lima_met": int(g["clase"].isin(["moderna", "lima_met"]).sum()),
                        "moderna": int((g["clase"] == "moderna").sum())})

    # ── padrón shares ────────────────────────────────────────────────────────
    roll = pd.read_csv(META26 / "peru_2026_distrito_electoral_roll.csv")
    roll["dist_norm"] = roll["nombre_distrito"].map(norm)
    padron_total = int(roll["num_electores"].sum())
    mask_limamet = (roll["ubigeo_provincia"] == 140100) | (roll["nombre_dept"] == "CALLAO")
    mask_moderna = (roll["ubigeo_provincia"] == 140100) & roll["dist_norm"].isin(LIMA_MODERNA)
    padron_limamet = int(roll.loc[mask_limamet, "num_electores"].sum())
    padron_moderna = int(roll.loc[mask_moderna, "num_electores"].sum())

    # ── senator count per domicile district (map dots + table) ───────────────
    por_distrito = (sen.dropna(subset=["domi_dist"])
                    .groupby(["domi_dep", "domi_prov", "domi_dist"]).size()
                    .reset_index(name="senadores")
                    .sort_values("senadores", ascending=False))

    def counts(df):
        c = df["clase"].value_counts()
        return {k: int(c.get(k, 0)) for k in ["moderna", "lima_met", "pais", "exterior"]}

    agregados = {
        "definicion_lima_moderna": LIMA_MODERNA,
        "padron": {"total": padron_total, "lima_met": padron_limamet,
                   "lima_moderna": padron_moderna},
        "senado": {
            "total": counts(sen),
            "por_modalidad": {m: counts(g) for m, g in sen.groupby("modalidad")},
            "departamental_en_su_dep": int(sen["en_su_dep"].sum()),
            "departamental_n": int((sen["modalidad"] == "departamental").sum()),
            "por_distrito": por_distrito.to_dict(orient="records"),
        },
        "candidatos_nacional": {
            "inscritos": int(len(uni)),
            "con_hdv": int(len(con)),
            "sin_hdv": int(uni["clase"].isna().sum()),
            "total": counts(con),
            "por_posicion": por_pos,
        },
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
    out_gj = {"type": "FeatureCollection", "features": feats}
    (OUT / "lima_met_distritos.geojson").write_text(
        json.dumps(out_gj, ensure_ascii=False, separators=(",", ":")))

    print(f"senadores.json: {len(senadores)} · agregados.json · "
          f"lima_met_distritos.geojson: {len(feats)} distritos "
          f"({(OUT/'lima_met_distritos.geojson').stat().st_size/1e3:.0f} KB)")
    print("senado:", agregados["senado"]["total"],
          "| candidatos:", agregados["candidatos_nacional"]["total"])


if __name__ == "__main__":
    main()
