#!/usr/bin/env python3
"""Parte el buscador de candidatos en trozos por circunscripción.

El buscador del artículo `erm-2026-candidatos` sirve un solo `candidatos.json`
de **11 MB** con las 101,948 candidaturas. En un artículo eso está bien: quien
entra ahí va a buscar, y lo paga una vez.

En la página de resultados no. Esa noche se esperan 20,000 concurrentes y el
presupuesto de la fase 07 son dos segundos en 3G. Si uno de cada diez abre la
pestaña, son 22 GB de transferencia contra el límite de GitHub Pages: el riesgo
no es que el buscador vaya lento, es que tumbe el sitio entero.

La estructura ya venía resuelta: `circ[tipo][ubigeo]` es exactamente un trozo por
circunscripción. Aquí se escribe cada uno en su archivo y un índice ligero con
la cascada de nombres —tipo, departamento, provincia, distrito— que es lo único
que hace falta para armar los desplegables.

La interfaz del buscador no cambia. Lo único que cambia es que pide el trozo de
la circunscripción elegida en vez de traerse el país entero.

**Solo pasa lo inscrito.** El artículo sirve el registro entero —listas
improcedentes, tachadas, retiradas, y dentro de las inscritas los candidatos
excluidos o renunciados— porque ahí el tema es el registro mismo. En la página
de resultados la pregunta es otra: quién está en carrera. Una lista improcedente
como la de Integridad Democrática en Lima provincial no compite, y mostrarla
junto a las que sí compiten confunde.

Cuidado con leerlo de más: `REGLAS-ELECTORALES.md` dice que esas listas
**cuentan votos pero no reciben escaños**. Lo que se filtra aquí es el
directorio de candidatos, no el cómputo: si la ONPE reporta votos de una lista
improcedente, la tabla de resultados los muestra igual.

Uso:
    uv run python scripts/01a_publica_candidatos.py
    uv run python scripts/01a_publica_candidatos.py --fuente <ruta a candidatos.json>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FUENTE = Path(
    RAIZ.parents[1] / "articulos/erm-2026-candidatos"
    "/buscador/data/candidatos.json"
)

# El único estado que sigue en carrera. El JNE usa además IMPROCEDENTE, TACHADO,
# RETIRO, RENUNCIA, EXCLUSION y FALLECIDO; ninguno compite. Se compara por
# igualdad exacta, no por subcadena: así un estado nuevo que el JNE invente
# queda fuera y se ve en el conteo de descartes, en vez de colarse en silencio.
INSCRITO = "INSCRITO"

CABEZA = ("GOBERNADOR", "ALCALDE")


def filtra(circ: dict, ix: dict[str, int], descartes: dict) -> dict | None:
    """Deja solo listas y candidatos inscritos. None si no queda nada."""
    i_estado, i_sexo, i_cargo = ix["estado"], ix["sexo"], ix["cargo"]
    listas = []
    for lista in circ.get("listas") or []:
        cands_orig = lista.get("cands") or []
        if lista.get("estado") != INSCRITO:
            descartes["listas"][lista.get("estado") or "SIN ESTADO"] += 1
            descartes["cands_de_listas_fuera"] += len(cands_orig)
            continue
        cands = [c for c in cands_orig if c[i_estado] == INSCRITO]
        for c in cands_orig:
            if c[i_estado] != INSCRITO:
                descartes["cands"][c[i_estado] or "SIN ESTADO"] += 1
        if not cands:
            # No se ha visto, pero si pasa es noticia: una lista inscrita sin un
            # solo candidato en carrera no se publica muda.
            descartes["listas_vaciadas"] += 1
            continue
        lista = dict(lista, cands=cands)
        # h/m y cabeza venían calculados sobre la lista entera. Recalcularlos es
        # obligatorio: si no, el resumen cuenta gente que la tabla ya no muestra.
        lista["h"] = sum(1 for c in cands if c[i_sexo] == "M")
        lista["m"] = sum(1 for c in cands if c[i_sexo] == "F")
        cab = next((c for c in cands
                    if (c[i_cargo] or "").upper().startswith(CABEZA)), None)
        if cab is None:
            # Unas 545 listas inscritas llevan al gobernador o al alcalde
            # fuera de carrera. La lista compite igual —sus votos cuentan— pero
            # aquí no hay a quién poner de cabeza, y no se inventa uno con el
            # primer regidor: el encabezado queda vacío.
            lista.pop("cabeza", None)
            descartes["listas_sin_cabeza"] += 1
        else:
            lista["cabeza"] = {"nombre": cab[ix["nombre"]],
                               "cargo": cab[i_cargo], "dni": cab[ix["dni"]]}
        listas.append(lista)
    if not listas:
        return None
    return dict(circ, listas=listas)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--fuente", type=Path, default=FUENTE)
    ap.add_argument("--out", type=Path, default=RAIZ / "data/candidatos")
    args = ap.parse_args()

    if not args.fuente.exists():
        print(f"no existe la fuente: {args.fuente}", file=sys.stderr)
        return 1

    d = json.loads(args.fuente.read_text(encoding="utf-8"))

    campos = d.get("cand_campos") or []
    faltan = [k for k in ("nombre", "dni", "cargo", "sexo", "estado")
              if k not in campos]
    if faltan:
        print(f"la fuente no trae {', '.join(faltan)} en cand_campos: "
              f"{campos}", file=sys.stderr)
        return 1
    ix = {k: campos.index(k) for k in campos}

    # Se reescribe entero cada vez: el registro del JNE cambia de un día a otro
    # y un trozo viejo que sobreviva a la reconstrucción es una lista fantasma.
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    indice: dict[str, dict] = {}
    n_trozos = n_listas = n_cands = 0
    peso = 0
    descartes = {
        "listas": Counter(), "cands": Counter(), "cands_de_listas_fuera": 0,
        "listas_vaciadas": 0, "listas_sin_cabeza": 0, "circ_vacias": [],
    }

    for tipo, circs in (d.get("circ") or {}).items():
        entradas = []
        for ubi, c in circs.items():
            c = filtra(c, ix, descartes)
            if c is None:
                # Una circunscripción sin una sola lista inscrita no se publica:
                # no hay trozo que pedir y el desplegable no debe ofrecerla.
                descartes["circ_vacias"].append(f"{tipo}-{ubi}")
                continue
            trozo = args.out / f"{tipo}-{ubi}.json"
            texto = json.dumps(c, ensure_ascii=False, separators=(",", ":"))
            trozo.write_text(texto, encoding="utf-8")
            peso += len(texto.encode("utf-8"))
            n_trozos += 1
            listas = c.get("listas") or []
            n_listas += len(listas)
            n_cands += sum(len(x.get("cands") or []) for x in listas)
            # El índice lleva solo lo que arma los desplegables. Meter aquí el
            # número de listas tentaba, pero son 2,118 enteros más en el archivo
            # que se carga siempre, para un dato que se ve al abrir el trozo.
            entradas.append({
                "ubi": ubi,
                "dep": c.get("dep", ""),
                "prov": c.get("prov", ""),
                "dist": c.get("dist", ""),
            })
        entradas.sort(key=lambda e: (e["dep"], e["prov"], e["dist"]))
        indice[tipo] = entradas

    # Los totales se cuentan aquí, no se copian de la fuente: los de la fuente
    # son del registro entero y la cabecera del buscador quedaría diciendo
    # 101,948 candidaturas sobre una tabla que muestra 89,492.
    doc = {
        "generado": datetime.now(timezone.utc).astimezone().isoformat(),
        "origen_generado": d.get("generado"),
        "total_candidatos": n_cands,
        "total_listas": n_listas,
        "solo_inscritos": True,
        "cand_campos": d.get("cand_campos"),
        "tipos": d.get("tipos"),
        "circ": indice,
    }
    ind = args.out / "indice.json"
    ind.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    kb_ind = ind.stat().st_size / 1024
    print(f"{n_trozos:,} circunscripciones · {n_listas:,} listas · "
          f"{n_cands:,} candidatos   (solo inscritos)")
    print(f"  índice   {kb_ind:>8.1f} KB   (se carga siempre)")
    print(f"  trozos   {peso/1_048_576:>8.1f} MB   "
          f"({peso/max(1,n_trozos)/1024:.1f} KB de media, se carga uno)")

    # El descarte se reporta entero. Es el único sitio donde se ve que el
    # buscador de la noche muestra menos que el registro, y por qué.
    dl, dc = descartes["listas"], descartes["cands"]
    print(f"\ndescartado por estado ante el JNE:")
    print(f"  listas   {sum(dl.values()):>8,}   " +
          ", ".join(f"{k} {v:,}" for k, v in dl.most_common()))
    print(f"           {descartes['cands_de_listas_fuera']:>8,}   "
          f"candidatos que iban en esas listas")
    print(f"  cands    {sum(dc.values()):>8,}   " +
          ", ".join(f"{k} {v:,}" for k, v in dc.most_common()) +
          "   (dentro de listas inscritas)")
    if descartes["listas_vaciadas"]:
        print(f"  ATENCIÓN: {descartes['listas_vaciadas']:,} listas inscritas "
              f"se quedaron sin un solo candidato en carrera")
    print(f"  {descartes['listas_sin_cabeza']:,} listas inscritas llevan al "
          f"gobernador o alcalde fuera de carrera: van sin cabeza")
    if descartes["circ_vacias"]:
        print(f"  ATENCIÓN: {len(descartes['circ_vacias'])} circunscripciones "
              f"sin ninguna lista inscrita, no se publican: "
              + ", ".join(descartes["circ_vacias"][:10]))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
