#!/usr/bin/env python3
"""Cómputo oficial → las páginas del sitio. Corre en cada ciclo.

Lee las dos tablas que deja `03_consolida_mesas.py` y **rellena los mismos
archivos que dejó `00g_prepobla.py` en cero**:

    data/carrera/{race_id}.json   computo, votos y % por lista, desagregado
    data/nacional.json            avance, participación, votos por tipo y por org

MODO: SOLO RESULTADOS
---------------------
Esta versión publica el cómputo de la ONPE tal cual y **no proyecta ni llama
carreras**: `pronostico` y `electos` se quedan en `por_definir`. Es el modo de
degradación «sin proyección» de la spec 07: el replay de 2022 no pasó su
criterio (15 llamadas mal, 17 retracciones), así que esta noche no se afirma un
ganador que la ONPE no haya terminado de contar.

CRUCE DE ORGANIZACIONES
-----------------------
Las páginas en cero usan el id del JNE (`jne-1257`); la ONPE trae su propio
código. El cruce, en este orden:

1. `data/reference/crosswalk_organizaciones_2026.csv` (`codigo_onpe,id_jne`), si
   existe: es el revisado a mano (`m1`).
2. Dentro de **cada carrera**, por nombre normalizado contra las listas que esa
   carrera tiene inscritas. Es exacto en la práctica —la ONPE y el JNE usan el
   nombre oficial de la organización— y no puede cruzar con una organización
   que no compite ahí.
3. Lo que no cruza **entra igual**, como `onpe-{código}` con el nombre de la
   ONPE, sin foto ni ficha, y queda en `processed/publica_sin_cruce.csv`. Ningún
   voto se descarta por no saber de quién es.

Es idempotente: cada corrida recalcula todo desde las tablas, así que el estado
de una página nunca depende de la corrida anterior.

Uso:
    uv run python scripts/04_publica_resultados.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RACE_COL = {"01": "race_gobernador", "02": "race_consejero",
            "03": "race_provincial", "04": "race_distrital"}
# Para los totales nacionales (emitidos, participación) se usa una sola elección
# que existe en todas las mesas: la provincial. Sumar los cuatro tipos contaría
# cada votante cuatro veces.
TIPO_NACIONAL = "03"
NIVEL_UBIGEO = {"departamento": lambda u: u[:2] + "0000",
                "provincia": lambda u: u[:4] + "00",
                "distrito": lambda u: u}


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def escribe(ruta: Path, obj) -> bool:
    """Atómica, y solo si cambió. Devuelve si escribió."""
    nuevo = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if ruta.exists() and ruta.read_text() == nuevo:
        return False
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(nuevo)
    tmp.replace(ruta)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=RAIZ / "data")
    a = ap.parse_args(argv)
    D = a.data

    f_comp = D / "processed/computo_mesa_ERM2026.parquet"
    f_res = D / "processed/resultados_mesa_ERM2026.parquet"
    if not f_comp.exists():
        print("no hay cómputo consolidado: corre 03_consolida_mesas.py primero")
        return 1
    comp = pd.read_parquet(f_comp)
    res = pd.read_parquet(f_res) if f_res.exists() else pd.DataFrame(
        columns=["mesa", "tipo", "ubigeo_distrito", "codigo_onpe", "agrupacion", "votos"])
    comp = comp[comp.race_id.notna()]
    C = comp[comp.estado_acta == "C"]

    # Actas esperadas por carrera y por unidad de desagregado, desde el maestro:
    # el avance de una provincia dentro de una gobernación se mide contra sus
    # propias mesas, no contra las de toda la región.
    mesas = pd.read_parquet(D / "processed/mesas.parquet").fillna("")
    esperadas_unidad = defaultdict(int)          # (race_id, nivel, ubigeo) -> mesas
    for t, col in RACE_COL.items():
        m = mesas[mesas[col] != ""]
        for nivel, f in NIVEL_UBIGEO.items():
            for (rid, u), n in m.groupby([m[col], m.ubigeo_distrito.map(f)]).size().items():
                esperadas_unidad[(rid, nivel, u)] += int(n)

    # Crosswalk revisado, si ya existe.
    cw = {}
    f_cw = D / "reference/crosswalk_organizaciones_2026.csv"
    if f_cw.exists():
        x = pd.read_csv(f_cw, dtype=str).dropna(subset=["codigo_onpe", "id_jne"])
        cw = {r.codigo_onpe: f"jne-{r.id_jne}" for r in x.itertuples()}

    # Agregados por carrera, de una sola pasada.
    comp_rid = C.groupby("race_id").agg(
        actas=("mesa", "size"), electores=("electores", "sum"), emitidos=("votaron", "sum"),
        validos=("votos_validos", "sum"), blancos=("votos_blancos", "sum"),
        nulos=("votos_nulos", "sum"), impugnados=("votos_impugnados", "sum")).to_dict("index")
    rid_de = C.set_index(["mesa", "tipo"]).race_id
    res = res.join(rid_de, on=["mesa", "tipo"], how="inner")
    votos_por_rid = defaultdict(dict)
    for (rid, cod, nom), v in res.groupby(["race_id", "codigo_onpe", "agrupacion"]).votos.sum().items():
        votos_por_rid[rid][(cod, nom)] = int(v)
    # (race_id, unidad) -> {codigo_onpe: votos} y -> actas contabilizadas, por nivel.
    unidad = {}
    for nivel, f in NIVEL_UBIGEO.items():
        vv = defaultdict(dict)
        g = res.assign(u=res.ubigeo_distrito.map(f)).groupby(["race_id", "u", "codigo_onpe"]).votos.sum()
        for (rid, u, cod), v in g.items():
            vv[(rid, u)][cod] = int(v)
        act = C.assign(u=C.ubigeo_distrito.map(f)).groupby(["race_id", "u"]).size().to_dict()
        unidad[nivel] = (vv, act)

    ahora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    sin_cruce, escritos = [], 0
    votos_org_tipo = defaultdict(lambda: defaultdict(int))     # codigo -> tipo -> votos
    validos_tipo = defaultdict(int)
    resumen_rid = {}

    for f in sorted((D / "carrera").glob("*.json")):
        doc = json.loads(f.read_text())
        rid, tipo = doc["race_id"], doc["tipo"]
        # Idempotencia: se quitan las listas que una corrida anterior agregó
        # sin cruce y se ponen a cero las demás antes de recalcular.
        doc["organizaciones"] = [o for o in doc["organizaciones"]
                                 if not str(o["codigo"]).startswith("onpe-")]
        por_nombre = {norm(o["nombre"]): o for o in doc["organizaciones"]}
        por_codigo = {o["codigo"]: o for o in doc["organizaciones"]}
        for o in doc["organizaciones"]:
            o["votos"], o["pct_validos"] = 0, 0.0

        onpe_a_cod = {}
        for (cod_onpe, nombre), v in votos_por_rid.get(rid, {}).items():
            o = por_codigo.get(cw.get(cod_onpe)) or por_nombre.get(norm(nombre))
            if o is None:
                o = {"codigo": f"onpe-{cod_onpe}", "nombre": nombre, "logo": None,
                     "candidato": None, "votos": 0, "pct_validos": 0.0,
                     "p_gana": None, "p_primera": None, "p_segunda": None}
                doc["organizaciones"].append(o)
                por_codigo[o["codigo"]] = o
                sin_cruce.append({"race_id": rid, "codigo_onpe": cod_onpe,
                                  "agrupacion": nombre, "votos": int(v)})
            o["votos"] += int(v)
            onpe_a_cod[cod_onpe] = o["codigo"]

        cr = comp_rid.get(rid, {})
        validos = sum(o["votos"] for o in doc["organizaciones"])
        for o in doc["organizaciones"]:
            o["pct_validos"] = round(o["votos"] / validos, 6) if validos else 0.0
            votos_org_tipo[o["codigo"]][tipo] += o["votos"]
        validos_tipo[tipo] += validos
        doc["organizaciones"].sort(key=lambda o: (-o["votos"], o["nombre"]))

        esp = doc["computo"].get("actas_esperadas") or 0
        doc["computo"].update({
            "actas_contabilizadas": int(cr.get("actas", 0)),
            "pct_actas": round(cr.get("actas", 0) / esp, 6) if esp else 0.0,
            "electores_habiles": int(cr.get("electores", 0)),
            "votos_emitidos": int(cr.get("emitidos", 0)),
            "votos_validos": int(validos),
            "votos_blancos": int(cr.get("blancos", 0)),
            "votos_nulos": int(cr.get("nulos", 0)),
            "votos_impugnados": int(cr.get("impugnados", 0)),
        })

        for nivel, filas in doc.get("desagregado_niveles", {}).items():
            vot, act = unidad[nivel]
            for x in filas:
                u = x["ubigeo"]
                n_act = int(act.get((rid, u), 0))
                n_esp = esperadas_unidad.get((rid, nivel, u), 0)
                vv = {}
                for cod_onpe, v in vot.get((rid, u), {}).items():
                    k = onpe_a_cod.get(cod_onpe, f"onpe-{cod_onpe}")
                    vv[k] = vv.get(k, 0) + v
                x.update({"actas": n_act, "pct_actas": round(n_act / n_esp, 6) if n_esp else 0.0,
                          "votos": vv})
        if doc.get("desagregado_niveles"):
            doc["desagregado"] = doc["desagregado_niveles"][next(iter(doc["desagregado_niveles"]))]
        # El sello solo se mueve si cambió algo de la página: si no, cada ciclo
        # reescribiría las 2,118 y cada push arrastraría miles de archivos.
        previo = json.loads(f.read_text())
        previo.pop("actualizado", None)
        sin_sello = {k: v for k, v in doc.items() if k != "actualizado"}
        if json.dumps(previo, sort_keys=True) != json.dumps(sin_sello, sort_keys=True):
            doc["actualizado"] = ahora
            escritos += escribe(f, doc)
        resumen_rid[rid] = doc["computo"]["pct_actas"]

    # --- nacional
    nac = json.loads((D / "nacional.json").read_text())
    esp_tot = nac.get("actas_esperadas") or 0
    n_contab = int(len(C))
    nt = C[C.tipo == TIPO_NACIONAL]
    elec_esc, emit = int(nt.electores.sum()), int(nt.votaron.sum())
    nac.update({
        "generado": ahora, "version": int(nac.get("version", 0)) + 1,
        "pct": round(n_contab / esp_tot, 6) if esp_tot else 0.0,
        "actas_contabilizadas": n_contab,
        "electores_escrutados": elec_esc,
        "votos_emitidos": emit,
        "votos_validos": int(nt.votos_validos.sum()),
        "participacion": round(emit / elec_esc, 6) if elec_esc else None,
        "votos_validos_tipo": dict(validos_tipo),
        "modo": "solo_resultados",
    })
    if not nac.get("electores_habiles"):
        loc = D / "reference/locales.csv"
        if loc.exists():
            l = pd.read_csv(loc)
            col = next((c for c in l.columns if "elector" in c.lower()), None)
            if col:
                nac["electores_habiles"] = int(pd.to_numeric(l[col], errors="coerce").sum())
    for c in nac.get("por_carrera", []):
        c["pct_actas"] = resumen_rid.get(c["race_id"], c.get("pct_actas", 0.0))
    for o in nac.get("por_organizacion", []):
        o["votos"] = dict(votos_org_tipo.get(o["codigo"], {}))
    escribe(D / "nacional.json", nac)

    pd.DataFrame(sin_cruce, columns=["race_id", "codigo_onpe", "agrupacion", "votos"]).to_csv(
        D / "processed/publica_sin_cruce.csv", index=False)
    print(f"{escritos:,} páginas reescritas · actas contabilizadas {n_contab:,} "
          f"({100 * nac['pct']:.2f}%) · listas sin cruce {len(sin_cruce)}")
    if sin_cruce:
        print("  sin cruce -> processed/publica_sin_cruce.csv (entran con el nombre de la ONPE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
