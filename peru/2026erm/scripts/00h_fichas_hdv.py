#!/usr/bin/env python3
"""Fichas de hoja de vida, una por carrera → `data/hdv/{race_id}.json`.

POR QUÉ APARTE DEL CONTRATO
---------------------------
La ficha completa de un candidato son varios kilobytes: educación, experiencia
laboral, cargos anteriores, sentencias, ingresos y bienes. Meterla en
`carrera/{race_id}.json` multiplicaría por diez el peso de la página que se
descarga en cada sondeo, para un dato que solo se mira cuando alguien pulsa «Ver
hoja de vida».

Así que va en archivos aparte, uno por carrera, que el cliente pide **una sola
vez y bajo demanda**. Y no se regeneran en la noche: la hoja de vida de un
candidato no cambia porque lleguen actas.

QUÉ SE EXTRAE
-------------
Todo lo que el JNE publica y se puede leer de un vistazo. Lo que no declaró sale
como lista vacía, **nunca como cero**: no es lo mismo «no tiene sentencias» que
«no llenó esa sección», y la ficha lo distingue con `declara`.

Uso:
    uv run python scripts/00h_fichas_hdv.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zlib
from collections import defaultdict
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]


def si(v) -> bool:
    return str(v or "").strip() in ("1", "S", "SI", "SÍ", "true", "True")


def txt(v) -> str:
    return " ".join(str(v or "").split())


def num(v):
    try:
        n = float(v)
        return n if n else None
    except (TypeError, ValueError):
        return None


def rango(a, b) -> str:
    a, b = txt(a), txt(b)
    if a and b:
        return a if a == b else f"{a}–{b}"
    return a or b or ""


def extrae(d: dict) -> dict:
    """El JSON crudo del JNE → la ficha que consume la página."""
    g = lambda k: d.get(k) or []          # noqa: E731
    o = lambda k: d.get(k) or {}          # noqa: E731

    bas, tec, nouni = o("oEduBasica"), o("oEduTecnico"), o("oEduNoUniversitaria")
    educacion = {
        "primaria": si(bas.get("strEduPrimaria")),
        "primaria_concluida": si(bas.get("strConcluidoEduPrimaria")),
        "secundaria": si(bas.get("strEduSecundaria")),
        "secundaria_concluida": si(bas.get("strConcluidoEduSecundaria")),
        "tecnica": ([{"centro": txt(tec.get("strCenEstudioTecnico")),
                      "carrera": txt(tec.get("strCarreraTecnico")),
                      "concluida": si(tec.get("strConcluidoEduTecnico"))}]
                    if si(tec.get("strTengoEduTecnico")) else []),
        "no_universitaria": ([{"centro": txt(nouni.get("strCentroEstudioNoUni")),
                               "carrera": txt(nouni.get("strCarreraNoUni")),
                               "concluida": si(nouni.get("strConcluidoNoUni"))}]
                             if si(nouni.get("strTengoNoUniversitaria")) else []),
        "universitaria": [
            {"centro": txt(x.get("strUniversidad")),
             "carrera": txt(x.get("strCarreraUni")),
             "concluida": si(x.get("strConcluidoEduUni")),
             "egresado": si(x.get("strEgresadoEduUni")),
             "bachiller": txt(x.get("strAnioBachiller")),
             "titulo": txt(x.get("strAnioTitulo"))}
            for x in g("lEduUniversitaria") if txt(x.get("strUniversidad"))],
        "posgrado": [
            {"centro": txt(x.get("strCenEstudioPosgrado")),
             "especialidad": txt(x.get("strEspecialidadPosgrado")),
             "anio": txt(x.get("strAnioPosgrado")),
             "concluido": si(x.get("strConcluidoPosgrado")),
             "maestro": si(x.get("strEsMaestro")),
             "doctor": si(x.get("strEsDoctor"))}
            for x in g("lEduPosgrado") if txt(x.get("strCenEstudioPosgrado"))],
    }

    ing = o("oIngresos")
    ingresos = None
    if si(ing.get("strTengoIngresos")):
        ingresos = {
            "anio": txt(ing.get("strAnioIngresos")),
            "remuneracion_publica": num(ing.get("decRemuBrutaPublico")),
            "remuneracion_privada": num(ing.get("decRemuBrutaPrivado")),
            "renta_publica": num(ing.get("decRentaIndividualPublico")),
            "renta_privada": num(ing.get("decRentaIndividualPrivado")),
            "otros_publico": num(ing.get("decOtroIngresoPublico")),
            "otros_privado": num(ing.get("decOtroIngresoPrivado")),
        }
        ingresos["total"] = sum(v for k, v in ingresos.items()
                                if k != "anio" and v) or None

    return {
        "educacion": educacion,
        "experiencia": [
            {"centro": txt(x.get("strCentroTrabajo")),
             "ocupacion": txt(x.get("strOcupacionProfesion")),
             "lugar": " / ".join(t for t in (txt(x.get("strTrabajoDepartamento")),
                                             txt(x.get("strTrabajoProvincia")),
                                             txt(x.get("strTrabajoDistrito"))) if t),
             "anios": rango(x.get("strAnioTrabajoDesde"), x.get("strAnioTrabajoHasta"))}
            for x in g("lExperienciaLaboral") if txt(x.get("strCentroTrabajo"))],
        # `strCargoEleccion` trae un "1" —es la bandera de «tengo cargos»— y el
        # nombre real está en `strCargoEleccion2`. Sin esto la ficha listaba
        # cargos llamados «1».
        "cargos_eleccion": [
            {"cargo": txt(x.get("strCargoEleccion2")) or txt(x.get("strCargoEleccion")),
             "organizacion": txt(x.get("strOrgPolCargoElec")),
             "anios": rango(x.get("strAnioCargoElecDesde"),
                            x.get("strAnioCargoElecHasta"))}
            for x in g("lCargoEleccion")
            if txt(x.get("strCargoEleccion2")) or txt(x.get("strCargoEleccion"))],
        "cargos_partidarios": [
            {"cargo": txt(x.get("strCargoPartidario")),
             "organizacion": txt(x.get("strOrgPolCargoPartidario")),
             "anios": rango(x.get("strAnioCargoPartiDesde"),
                            x.get("strAnioCargoPartiHasta"))}
            for x in g("lCargoPartidario") if txt(x.get("strCargoPartidario"))],
        "renuncias": [
            {"organizacion": txt(x.get("strOrgPolRenunciaOP")),
             "anio": txt(x.get("strAnioRenunciaOP"))}
            for x in g("lRenunciaOP") if txt(x.get("strOrgPolRenunciaOP"))],
        "sentencias_penales": [
            {"delito": txt(x.get("strDelitoPenal")),
             "expediente": txt(x.get("strExpedientePenal")),
             "organo": txt(x.get("strOrganoJudiPenal")),
             "fecha": txt(x.get("strFechaSentenciaPenal")),
             "fallo": txt(x.get("strFalloPenal")),
             "modalidad": txt(x.get("strModalidad")),
             "cumplimiento": txt(x.get("strCumpleFallo"))}
            for x in g("lSentenciaPenal") if txt(x.get("strExpedientePenal"))],
        "sentencias_obligaciones": [
            {"materia": txt(x.get("strMateriaSentencia")),
             "expediente": txt(x.get("strExpedienteObliga")),
             "organo": txt(x.get("strOrganoJuridicialObliga")),
             "fallo": txt(x.get("strFalloObliga"))}
            for x in g("lSentenciaObliga") if txt(x.get("strExpedienteObliga"))],
        "ingresos": ingresos,
        "inmuebles": [
            {"tipo": txt(x.get("strTipoBienInmueble")),
             "lugar": txt(x.get("strInmuebleDireccion")),
             "valor": num(x.get("decValor")) or num(x.get("decAutovaluo"))}
            for x in g("lBienInmueble") if txt(x.get("strTipoBienInmueble"))],
        "muebles": [
            {"tipo": txt(x.get("strVehiculo")) or txt(x.get("strCaracteristica")),
             "detalle": " ".join(t for t in (txt(x.get("strMarca")),
                                             txt(x.get("strModelo")),
                                             txt(x.get("strAnio"))) if t),
             "valor": num(x.get("decValor"))}
            for x in g("lBienMueble")
            if txt(x.get("strVehiculo")) or txt(x.get("strCaracteristica"))],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hdv", type=Path, default=RAIZ.parents[1] / "articulos/erm-2026-candidatos/data/hdv/hdv_erm2026.sqlite")
    p.add_argument("--inscritos", type=Path,
                   default=RAIZ / "data/processed/candidatos_inscritos.parquet")
    p.add_argument("--out", type=Path, default=RAIZ / "data/hdv")
    a = p.parse_args()

    ins = pd.read_parquet(a.inscritos)
    ins = ins[ins.hoja_vida_id.notna()]
    # cand_id -> (race_id, hoja_vida_id)
    por_carrera = defaultdict(dict)
    quiero = {}
    for r in ins.itertuples():
        quiero.setdefault(str(r.hoja_vida_id), []).append((r.race_id, str(r.cand_id)))
    print(f"candidaturas con hoja de vida: {len(ins):,} "
          f"en {ins.race_id.nunique():,} carreras")

    con = sqlite3.connect(f"file:{a.hdv}?mode=ro", uri=True)
    hechas = 0
    for hv, gz in con.execute("SELECT hoja_vida_id, gz FROM raw"):
        destinos = quiero.get(str(hv))
        if not destinos:
            continue
        try:
            d = json.loads(zlib.decompress(gz)).get("data") or {}
        except Exception:
            continue
        ficha = extrae(d)
        for rid, cid in destinos:
            por_carrera[rid][cid] = ficha
        hechas += 1
    con.close()
    print(f"fichas extraídas: {hechas:,}")

    a.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for rid, fichas in por_carrera.items():
        ruta = a.out / f"{rid}.json"
        with open(ruta, "w") as fh:
            json.dump(fichas, fh, ensure_ascii=False, separators=(",", ":"))
        total += ruta.stat().st_size
    tam = sorted(((f.stat().st_size, f.name) for f in a.out.glob("*.json")),
                 reverse=True)
    print(f"escritos {len(por_carrera):,} archivos · {total/1e6:.1f} MB")
    print("  los tres más pesados:")
    for n, nom in tam[:3]:
        print(f"    {nom:<22}{n/1e3:>8.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
