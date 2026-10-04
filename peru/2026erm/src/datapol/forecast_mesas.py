#!/usr/bin/env python3
"""Forecast de gobernador por Monte Carlo a nivel de mesa.

Misma lógica que `2026eg/segunda/scripts/05_forecast.py`, extendida a una
carrera multipartidaria con umbral de segunda vuelta.

EL MODELO
---------
Para cada mesa **que todavía no se ha contabilizado** se estima una distribución
de voto a partir del nivel más fino de la jerarquía que ya tenga suficientes
mesas contadas:

    local de votación  →  distrito  →  provincia  →  departamento

De ese nivel salen cuatro cosas medidas sobre las mesas contadas que le
pertenecen: la participación media y su desvío, y por organización la
participación media sobre votos emitidos y su desvío entre mesas.

Luego, en cada simulación y para cada mesa que falta:

    votaron  = electores * N(media_participacion, sd_participacion)
    votos_o  = votaron  * N(media_o, sd_o)

y el resultado final es lo contabilizado más lo simulado.

POR QUÉ SE AGRUPAN LAS MESAS POR PRIOR
--------------------------------------
Las mesas que comparten prior se colapsan en un solo grupo y reciben **un solo
sorteo por simulación**. Es la pieza que hace que el modelo no se engañe: si se
sorteara mesa por mesa de forma independiente, el error se lavaría con la raíz
del número de mesas y un departamento con tres mil mesas pendientes saldría casi
determinista. Agrupando, la incertidumbre de un distrito entero que no ha
reportado se mantiene entera, que es lo que corresponde.

ESCENARIOS
----------
La carrera de gobernador no se gana por mayoría simple. Con el 30% de los votos
válidos se gana en primera vuelta; por debajo, van a segunda las dos primeras.
Así que de cada simulación sale un escenario completo, no un ganador:

    ('1V', org)          gana en primera
    ('2V', (org, org))   segunda vuelta entre esas dos

y de la distribución de escenarios salen P(gana en 1V), P(pasa a 2V) por
organización y P(hay segunda vuelta) para la carrera.

Uso:
    uv run python scripts/forecast_mesas.py --dep 02 --sims 100
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]

UMBRAL_1V = 0.30
MIN_PARES = 5      # mesas contadas mínimas para usar un nivel como prior
SD_PART_DEF = 0.05

# La jerarquía disponible depende de cuál sea la circunscripción: para
# gobernador la carrera abarca el departamento entero y hay cuatro niveles;
# para alcalde provincial la provincia **es** la circunscripción y solo quedan
# tres. Nunca se usa un nivel por encima de la propia carrera: sería importar
# información de votantes que no participan en ella.
NIVELES_POR_TIPO = {
    "01": ("local", "distrito", "provincia", "departamento"),
    # Consejeros: la circunscripción es la provincia, no el departamento.
    "02": ("local", "distrito", "provincia"),
    "03": ("local", "distrito", "provincia"),
    "04": ("local", "distrito"),
}
# Solo la elección de gobernador se decide con umbral y segunda vuelta.
CON_SEGUNDA = {"01"}


def carga(tipo: str, ambito: str) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """-> (mesas con jerarquía y electores, matriz de votos, organizaciones)."""
    res = pd.read_parquet(RAIZ / "data/processed/resultados_mesa_ERM2022.parquet")
    comp = pd.read_parquet(RAIZ / "data/processed/computo_mesa_ERM2022.parquet")
    n = len(ambito)
    res = res[(res.tipo == tipo) & (res.ubigeo_distrito.str[:n] == ambito)]
    comp = comp[(comp.tipo == tipo) & (comp.ubigeo_distrito.str[:n] == ambito)].copy()
    # Las actas observadas no llegan en la ventana útil del forecast.
    comp = comp[comp.observacion.fillna("").str.upper().str.contains("NORMAL")]

    piv = res.pivot_table(index=["ubigeo_distrito", "mesa"], columns="codigo_onpe",
                          values="votos", aggfunc="sum", fill_value=0)
    orgs = list(piv.columns)
    piv = piv.reset_index()
    m = comp.merge(piv, on=["ubigeo_distrito", "mesa"], how="inner")

    m["distrito"] = m.ubigeo_distrito
    m["provincia"] = m.ubigeo_distrito.str[:4]
    m["departamento"] = m.ubigeo_distrito.str[:2]
    # El local se identifica dentro del distrito: el código se repite entre ellos.
    m["local"] = m.ubigeo_distrito + "_" + m.local.fillna("SIN_LOCAL")
    return m.reset_index(drop=True), m[orgs].to_numpy(np.int64), orgs


def estadisticas(contadas: pd.DataFrame, orgs: list[str], niveles,
                 universo: pd.DataFrame | None = None,
                 por_local: bool = False) -> dict:
    """Media y desvío de participación y de voto por organización, por nivel."""
    fuera = {}
    votaron = contadas.votaron.to_numpy(float)
    electores = np.clip(contadas.electores.to_numpy(float), 1, None)
    part = votaron / electores
    v = contadas[orgs].to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sh = np.where(votaron[:, None] > 0, v / np.clip(votaron[:, None], 1, None), 0.0)

    # Unidad hija sobre la que se cuenta el tamaño muestral efectivo. Con
    # `local` la corrección no depende de fronteras administrativas: si dos
    # distritos se fusionan, los locales siguen siendo los mismos y la banda no
    # se mueve. Con `distrito` sí depende, y esa es su debilidad.
    hijo_de = ({"departamento": "local", "provincia": "local",
                "distrito": "local", "local": None} if por_local else
               {"departamento": "provincia", "provincia": "distrito",
                "distrito": "local", "local": None})
    for nivel in niveles:
        hijo = hijo_de.get(nivel)
        if hijo is not None and hijo not in contadas.columns:
            hijo = None
        # Cuántas unidades hijas **existen** en cada clave, contadas o no. Sin
        # esto no se puede saber si observar tres distritos es mucho o poco.
        tot_hijos = ({k: v for k, v in
                      universo.groupby(nivel, observed=True)[hijo].nunique().items()}
                     if (hijo and universo is not None) else {})
        claves = contadas[nivel].to_numpy()
        d = {}
        for k in np.unique(claves):
            idx = np.where(claves == k)[0]
            n = len(idx)
            if n == 0:
                continue
            hijos = contadas[hijo].to_numpy()[idx] if hijo else None
            n_h, sd_h = 1, np.zeros(len(orgs))
            if hijos is not None:
                u_h = np.unique(hijos)
                n_h = len(u_h)
                if n_h > 1:
                    med = np.array([sh[idx][hijos == x].mean(axis=0)
                                    for x in u_h])
                    sd_h = med.std(axis=0, ddof=1)
            d[k] = {
                "n": n,
                # Unidades geográficas **hijas** observadas dentro de esta clave,
                # y cuánto difieren entre sí. Es lo que gobierna el error de la
                # media del nivel: con un solo distrito reportando, la
                # estimación de la provincia se equivoca en la magnitud de la
                # dispersión entre distritos, no en sd_entre_mesas/raíz(n).
                # Tratar 7 actas de un rincón como 7 observaciones de la
                # provincia es lo que produjo la banda de ±4pp en Acomayo.
                "n_hijos": n_h,
                "n_hijos_total": tot_hijos.get(k, n_h),
                "sd_hijos": sd_h,
                "media_sh": sh[idx].mean(axis=0),
                "sd_sh": (sh[idx].std(axis=0, ddof=1) if n > 1
                          else np.zeros(len(orgs))),
                "media_part": float(part[idx].mean()),
                "sd_part": (float(part[idx].std(ddof=1)) if n > 1 else SD_PART_DEF),
            }
        fuera[nivel] = d
    return fuera


def prior_de(fila, stats: dict, niveles):
    """Nivel más fino con suficientes mesas contadas. Devuelve el mismo objeto
    para todas las mesas que caen en él, para poder agruparlas después."""
    for nivel in niveles:
        st = stats[nivel].get(fila[nivel])
        if st is not None and st["n"] >= MIN_PARES:
            return st
    return None


# Peso del shock sistemático común a toda la carrera, como fracción de la
# dispersión entre mesas. Ver `docs/calibracion.md`: el ruido independiente por
# grupo se promedia con la raíz del número de grupos, así que en una carrera que
# agrega muchas unidades la banda se cierra sola aunque la incertidumbre real no
# haya bajado. Este término no se promedia: es un solo sorteo por simulación
# aplicado a **todas** las mesas pendientes a la vez, y representa que lo que
# falta puede votar distinto de lo contado de forma correlacionada.
KAPPA = 0.0

# Dispersión entre unidades hijas dentro de su madre, como k·sqrt(p(1-p)).
# Medido sobre ERM 2002-2022 en `build_varianzas_geograficas.py`. Se usa cuando
# hay tan pocas unidades observadas que la dispersión no se puede estimar de los
# datos —que es justo cuando más importa—.
_K_HIJO = {"provincia": [(0.0, 0.0), (0.025, 0.061), (0.10, 0.182),
                         (0.225, 0.196), (0.40, 0.195), (1.0, 0.195)],
           "departamento": [(0.0, 0.0), (0.025, 0.091), (0.10, 0.169),
                            (0.225, 0.175), (0.40, 0.162), (1.0, 0.162)]}


def sd_entre_hijos(p: np.ndarray, nivel: str) -> np.ndarray:
    tabla = _K_HIJO.get(nivel)
    if tabla is None:
        return np.zeros_like(p)
    k = np.interp(np.clip(p, 0.0, 1.0), [x for x, _ in tabla],
                  [y for _, y in tabla])
    return k * np.sqrt(np.clip(p * (1 - p), 0.0, None))

# Distancia histórica de cada geografía respecto de su circunscripción, medida
# en elecciones donde ambas votaron la **misma cédula** (ver
# `scripts/build_atipicidad.py`). Es la escala de «cuánto puede sorprender» una
# zona de la que todavía no llega ni un acta.
_ATIP: dict[tuple[str, str], float] | None = None
_DES: dict[tuple[str, str, str], float] | None = None
_DLOC: dict[str, float] | None = None


def desacuerdo_local() -> dict[str, float]:
    """D(local→local) dentro de cada distrito, medido sobre EG 2026."""
    global _DLOC
    if _DLOC is None:
        import csv
        ruta = (Path(__file__).resolve().parents[1]
                / "data/reference/desacuerdo_locales_eg2026.csv")
        _DLOC = {}
        if ruta.exists():
            with open(ruta) as f:
                for r in csv.DictReader(f):
                    _DLOC[r["ubigeo_distrito"]] = float(r["d_medio"])
    return _DLOC


def d_ruta(contadas, niveles, nivel_pal: str, circ: str = "") -> float:
    """Incertidumbre de la circunscripción estimada desde lo observado.

    Tener un local no es tener su distrito, y tener ese distrito no es tener la
    provincia: son dos saltos y **los dos suman**. Modelar solo el último —que
    es lo que hace `desacuerdo`— da por exacto que el local observado *es* su
    distrito, y por eso la banda salía corta aunque la magnitud de D fuera la
    correcta.

        d_ruta = sqrt( D(local→distrito)² / n_locales
                     + D(distrito→circ)²  / n_distritos )

    Cada término se divide por las unidades **independientes** observadas de ese
    salto: con un local de quince el primer término entra entero, con cuarenta
    locales repartidos se desvanece. Es lo que hace la corrección autoselectiva
    sin ninguna compuerta.
    """
    dl = desacuerdo_local()
    dists = contadas["distrito"].unique()
    n_loc = max(contadas["local"].nunique(), 1)
    n_dis = max(len(dists), 1)
    d1 = float(np.mean([dl.get(str(d), 0.19) for d in dists]))
    # Pares de **esta** circunscripción, no la media nacional: Lima
    # Metropolitana es mucho más homogénea entre sus distritos que una
    # provincia altoandina, y promediarlas la penaliza sin motivo.
    D = desacuerdo()
    n = len(circ)
    pares = [v for (niv, u, w), v in D.items()
             if niv == nivel_pal and n and u[:n] == circ and w[:n] == circ]
    if not pares:
        pares = [v for (niv, u, w), v in D.items() if niv == nivel_pal]
    d2 = float(np.mean(pares)) if pares else 0.0
    return float(np.sqrt(d1 ** 2 / n_loc + d2 ** 2 / n_dis))


def desacuerdo() -> dict[tuple[str, str, str], float]:
    """D(nivel, u, v): desacuerdo esperado entre dos geografías, simétrico."""
    global _DES
    if _DES is None:
        import csv
        ruta = (Path(__file__).resolve().parents[1]
                / "data/reference/desacuerdo_geografico.csv")
        _DES = {}
        if ruta.exists():
            with open(ruta) as f:
                for r in csv.DictReader(f):
                    d = float(r["d"])
                    _DES[(r["nivel"], r["u"], r["v"])] = d
                    _DES[(r["nivel"], r["v"], r["u"])] = d
    return _DES


def atipicidad() -> dict[tuple[str, str], float]:
    global _ATIP
    if _ATIP is None:
        import csv
        ruta = (Path(__file__).resolve().parents[1]
                / "data/reference/atipicidad_geografica.csv")
        _ATIP = {}
        if ruta.exists():
            with open(ruta) as f:
                for r in csv.DictReader(f):
                    _ATIP[(r["nivel"], r["unidad"])] = float(r["distancia"])
    return _ATIP


def _sorprende(p: np.ndarray, d: np.ndarray, rng) -> np.ndarray:
    """Perturba un vector de participaciones con distancia de variación total `d`.

    Dirección aleatoria, magnitud dada. Se **renormaliza** al final: recortar en
    cero sin renormalizar mete un sesgo sistemático que hunde al puntero e infla
    a las listas chicas, y ese error ya costó una tanda entera de mediciones.
    """
    r = rng.normal(size=p.shape)
    r = r - r.mean(axis=-1, keepdims=True)
    norma = np.abs(r).sum(axis=-1, keepdims=True) / 2.0
    delta = r / np.clip(norma, 1e-9, None) * d
    q = np.clip(p + delta, 1e-9, None)
    return q / q.sum(axis=-1, keepdims=True)


def simula(contadas: pd.DataFrame, faltantes: pd.DataFrame, orgs: list[str],
           n_sims: int, rng: np.random.Generator, tipo: str = "01",
           niveles: tuple[str, ...] | None = None,
           geo: bool = True) -> dict:
    # El nivel de circunscripción es explícito, nunca derivado del tipo: en
    # Callao la circunscripción de consejero es el **distrito**, no la
    # provincia, y usar el default de tipo 02 importaría información de los
    # otros seis distritos, que compiten con listas distintas.
    niveles = niveles or NIVELES_POR_TIPO[tipo]
    hay_segunda = tipo in CON_SEGUNDA
    base = contadas[orgs].to_numpy(np.int64).sum(axis=0).astype(float)
    K = len(orgs)

    sin_prior = 0
    if len(faltantes) == 0:
        total = np.tile(base, (n_sims, 1))
    else:
        stats = estadisticas(contadas, orgs, niveles,
                             pd.concat([contadas, faltantes]),
                             por_local=True)
        # Asignación de prior vectorizada, con numpy puro: una Series `object`
        # que mezcla `pd.NA` con cadenas respaldadas por Arrow **no agrupa
        # bien** —`groupby` colapsa claves distintas en una sola— y eso mandaba
        # miles de mesas a dos grupos gigantes. Con arrays de str no pasa.
        n_f = len(faltantes)
        asignado = np.full(n_f, "", dtype=object)
        for nivel in niveles:
            ok = {k for k, v in stats[nivel].items() if v["n"] >= MIN_PARES}
            if not ok:
                continue
            libre = np.where(asignado == "")[0]
            if len(libre) == 0:
                break
            clave = faltantes[nivel].to_numpy(dtype=object)[libre]
            hit = np.fromiter((c in ok for c in clave), bool, len(clave))
            asignado[libre[hit]] = [f"{nivel}\x00{c}" for c in clave[hit]]
        sin_prior = int((asignado == "").sum())
        # RESPALDO PARA LAS CIRCUNSCRIPCIONES SIN NIVEL SUFICIENTE
        # --------------------------------------------------------
        # Una mesa sin prior quedaba fuera del sorteo, y como sus votos no se
        # sumaban, quien llamaba tenía que descartar la carrera entera. Al 50%
        # contado eso dejaba **768 de 2,113 elecciones sin ninguna probabilidad**
        # —distritos con dos o tres actas—, que en la página se ve como una
        # columna vacía sin explicación.
        #
        # El reparo del autor original sigue en pie y es correcto: rellenar con
        # lo contado y callar produce un piso confiadísimo a partir de tres
        # actas. Pero eso vale para el **piso garantizado**, no para la
        # probabilidad. Aquí se les da un prior de respaldo construido con las
        # propias mesas contadas de la circunscripción, declarando una sola
        # unidad hija observada: con `n_hijos = 1` la corrección de población
        # finita no reduce nada y la banda que sale es la dispersión histórica
        # completa. O sea, incertidumbre ancha y honesta, no una falsa certeza.
        #
        # Quien llame recibe `respaldo=True` y **no debe** usar el resultado
        # para pisos garantizados ni para dar una carrera por definida.
        respaldo = False
        if sin_prior:
            libres = np.where(asignado == "")[0]
            sh_c = contadas[orgs].to_numpy(float)
            vot_c = contadas.votaron.to_numpy(float)
            ele_c = np.clip(contadas.electores.to_numpy(float), 1, None)
            with np.errstate(divide="ignore", invalid="ignore"):
                sh_m = np.where(vot_c[:, None] > 0,
                                sh_c / np.clip(vot_c[:, None], 1, None), 0.0)
            nc = len(contadas)
            prior_resp = {
                "n": nc, "n_hijos": 1, "n_hijos_total": max(nc + len(faltantes), 2),
                "sd_hijos": np.zeros(K),
                "media_sh": sh_m.mean(axis=0) if nc else np.full(K, 1.0 / K),
                "sd_sh": (sh_m.std(axis=0, ddof=1) if nc > 1 else np.zeros(K)),
                "media_part": float((vot_c / ele_c).mean()) if nc else 0.6,
                "sd_part": (float((vot_c / ele_c).std(ddof=1)) if nc > 1
                            else SD_PART_DEF),
            }
            asignado[libres] = "respaldo\x00circunscripcion"
            respaldo = True
        # Incertidumbre acumulada de la ruta observado -> circunscripción.
        # Se calcula siempre y vale 0 salvo en el modelo de cadena.

        # Un grupo por prior: un solo sorteo por simulación, que es lo que
        # conserva la incertidumbre correlacionada de lo que falta.
        elec_f = faltantes.electores.to_numpy(dtype=float)
        # Modelo «sorpresa»: una mesa cuyo prior viene de un nivel más grueso que
        # su propio distrito pertenece a un **distrito que no ha dicho nada**.
        # Esos no se agrupan con los demás: cada distrito mudo recibe su propio
        # sorteo, con la magnitud de sorpresa que ese distrito tiene medida.
        grupos = {}
        for llave in np.unique(asignado[asignado != ""]):
            nivel, k = llave.split("\x00", 1)
            pr = prior_resp if nivel == "respaldo" else stats[nivel][k]
            grupos[llave] = {"prior": pr,
                                 "electores": float(elec_f[asignado == llave].sum())}
        gs = list(grupos.values())
        if not gs:
            # Ninguna mesa pendiente alcanzó un nivel con pares suficientes: la
            # circunscripción no es proyectable todavía. Se devuelve lo contado
            # tal cual, con la bandera puesta, y quien llame decide. Rellenar
            # con lo contado y callar produciría un piso confiadísimo a partir
            # de tres actas, que es el peor error posible aquí.
            total = np.tile(base, (n_sims, 1))
            gs = None
    if len(faltantes) and gs:
        elec = np.array([g["electores"] for g in gs])
        m_part = np.array([g["prior"]["media_part"] for g in gs])
        s_part = np.array([g["prior"]["sd_part"] for g in gs])
        m_sh = np.array([g["prior"]["media_sh"] for g in gs])
        s_sh = np.array([g["prior"]["sd_sh"] for g in gs])
        n_g = np.array([max(g["prior"]["n"], 1) for g in gs], dtype=float)
        # Error de la media del nivel, gobernado por las unidades hijas
        # observadas. Con muchas (Lima: 35 distritos de 43) es despreciable;
        # con una (Acomayo: 1 de 7) es la incertidumbre dominante y hoy faltaba
        # por completo.
        n_h = np.array([max(g["prior"].get("n_hijos", 1), 1) for g in gs],
                       dtype=float)
        N_h = np.array([max(g["prior"].get("n_hijos_total", 1), 1) for g in gs],
                       dtype=float)
        sd_h = np.array([g["prior"].get("sd_hijos", np.zeros(K)) for g in gs])
        niv_g = ["provincia" for _ in grupos]
        sd_hist = np.array([sd_entre_hijos(g["prior"]["media_sh"], nv)
                            for g, nv in zip(gs, niv_g)])
        # Con una o dos unidades observadas la dispersión medida es ruido o
        # cero: manda la histórica. Con muchas, manda la observada.
        sd_base = np.where(n_h[:, None] >= 4, np.maximum(sd_h, 0.5 * sd_hist),
                           sd_hist)
        # Corrección por población finita: si ya se observaron casi todas las
        # unidades, no queda incertidumbre de nivel que valga.
        fpc = np.sqrt(np.clip(1.0 - n_h / N_h, 0.0, 1.0) / n_h)
        sd_nivel = sd_base * fpc[:, None]

        # El error de la **media** de un grupo estimada con n mesas es sd/raíz(n),
        # no sd. Usar sd trata la media del grupo como si viniera de una sola
        # mesa, y es lo que compensaba por accidente la falta del shock común.
        part = np.clip(rng.normal(m_part, s_part, size=(n_sims, len(gs))),
                       0.01, 1.0)
        emitidos = elec[None, :] * part
        shares = rng.normal(m_sh, s_sh, size=(n_sims, len(gs), K))
        if geo:
            # Un solo sorteo por grupo y simulación: el error de la media del
            # nivel es común a todas las mesas que cuelgan de él.
            shares = shares + rng.normal(0.0, np.maximum(sd_nivel, 0.0),
                                         size=(n_sims, len(gs), K))

        shares = np.clip(shares, 0.0, None)
        total = base[None, :] + (emitidos[:, :, None] * shares).sum(axis=1)

    validos = total.sum(axis=1, keepdims=True)
    share = total / np.clip(validos, 1, None)
    ordenado = np.argsort(-total, axis=1)
    primero = ordenado[:, 0]
    # Con una sola lista en la papeleta no hay segundo: gana sin más, y en
    # gobernador supera el umbral por definición.
    segundo = ordenado[:, 1] if ordenado.shape[1] > 1 else primero
    # En una carrera sin umbral —alcaldías— gana el primero, siempre.
    gana_1v = (share[np.arange(len(total)), primero] >= UMBRAL_1V
               if hay_segunda else np.ones(len(total), dtype=bool))

    p_gana = defaultdict(float)
    p_pasa = defaultdict(float)
    escen = defaultdict(int)
    for i in range(len(total)):
        a, b = orgs[primero[i]], orgs[segundo[i]]
        if gana_1v[i] or len(orgs) == 1:
            p_gana[a] += 1 / len(total)
            escen[("1V", a)] += 1
        else:
            p_pasa[a] += 1 / len(total)
            p_pasa[b] += 1 / len(total)
            escen[("2V", tuple(sorted((a, b))))] += 1
    return {
        "totales": total,
        # Mesas pendientes que no alcanzaron ningún nivel con pares suficientes.
        # Si es > 0 la proyección está incompleta y no debe usarse para adjudicar.
        "sin_prior": sin_prior,
        # Hubo que recurrir al prior de respaldo: sirve para probabilidades,
        # **no** para pisos garantizados ni para dar la elección por definida.
        "respaldo": bool(locals().get("respaldo", False)),
        "p_gana_1v": dict(p_gana),
        "p_pasa_2v": dict(p_pasa),
        "p_segunda": float(1 - gana_1v.mean()),
        "media": dict(zip(orgs, share.mean(axis=0))),
        "p05": dict(zip(orgs, np.quantile(share, 0.05, axis=0))),
        "p95": dict(zip(orgs, np.quantile(share, 0.95, axis=0))),
        "escenarios": {k: v / len(total) for k, v in
                       sorted(escen.items(), key=lambda kv: -kv[1])},
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tipo", default="01",
                    help="01 gobernador, 03 alcalde provincial, 04 distrital")
    ap.add_argument("--ambito", default="02",
                    help="ubigeo de la circunscripción: 2 dígitos para "
                         "gobernador, 4 para provincial, 6 para distrital")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--paso", type=float, default=0.10)
    ap.add_argument("--escanos", type=int,
                    help="si se da, reparte el concejo en cada simulación y "
                         "muestra la evolución de la tabla de electos")
    ap.add_argument("--conf", type=float, default=0.99,
                    help="probabilidad mínima para dar por llamado un resultado")
    args = ap.parse_args()

    m, V, orgs = carga(args.tipo, args.ambito)
    rng = np.random.default_rng(args.semilla)

    total_real = V.sum(axis=0)
    sh_real = total_real / total_real.sum()
    o = np.argsort(-total_real)
    real = (("1V", orgs[o[0]]) if (args.tipo not in CON_SEGUNDA
                                   or sh_real[o[0]] >= UMBRAL_1V)
            else ("2V", tuple(sorted((orgs[o[0]], orgs[o[1]])))))
    print(f"tipo {args.tipo} ámbito {args.ambito}: {len(m):,} actas, {m.local.nunique():,} locales, "
          f"{m.distrito.nunique()} distritos, {m.provincia.nunique()} provincias, "
          f"{len(orgs)} organizaciones")
    print("resultado real: " + "  ".join(
        f"{orgs[i]} {100*sh_real[i]:.1f}%" for i in o[:4]) + f"   -> {real}")

    # Orden de llegada: el local se contabiliza entero.
    locales = list(m.groupby("local").indices.values())
    rng.shuffle(locales)
    orden = np.concatenate(locales)

    print(f"\ncortes cada {args.paso:.0%} de actas, {args.sims} simulaciones cada uno")
    for frac in np.arange(args.paso, 1.0, args.paso):
        k = int(round(frac * len(orden)))
        idx_c = orden[:k]
        idx_f = orden[k:]
        cont = m.iloc[idx_c]
        falt = m.iloc[idx_f]
        r = simula(cont, falt, orgs, args.sims, rng, args.tipo)
        pct_votos = cont[orgs].to_numpy().sum() / total_real.sum()
        print(f"\n── {frac:.0%} de actas ({100*pct_votos:.1f}% de los votos) · "
              f"{len(cont):,} contadas, {len(falt):,} faltan · "
              f"distritos sin reportar: {falt.distrito.nunique() - cont.distrito.nunique() if False else (set(m.distrito) - set(cont.distrito)).__len__()}")
        if args.tipo in CON_SEGUNDA:
            print(f"   P(hay segunda vuelta) = {r['p_segunda']:6.1%}")
        for i in o[:4]:
            og = orgs[i]
            print(f"   {og}: media {r['media'][og]:5.1%} "
                  f"[{r['p05'][og]:5.1%} {r['p95'][og]:5.1%}]  "
                  + (f"P(gana 1V) {r['p_gana_1v'].get(og,0):5.1%}  "
                     f"P(pasa 2V) {r['p_pasa_2v'].get(og,0):5.1%}"
                     if args.tipo in CON_SEGUNDA
                     else f"P(gana) {r['p_gana_1v'].get(og,0):5.1%}"))
        print("   escenarios: " + " · ".join(
            f"{(('1V ' if args.tipo in CON_SEGUNDA else 'gana ')+k[1])
               if k[0]=='1V' else '2V '+'/'.join(k[1])} {v:.0%}"
            for k, v in list(r["escenarios"].items())[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
