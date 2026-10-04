"""Forecaster: distribución del resultado final dado el cómputo parcial.

No es una regla de irreversibilidad ni un umbral tabulado: **simula las mesas que
todavía no se han contabilizado** y devuelve la distribución del resultado, de la
que salen las probabilidades de victoria y las bandas.

EL MODELO
---------
Para una carrera con `m` de `M` mesas contadas y `V_u` votos por llegar:

  1. La propensión de voto del distrito es incierta. Su posterior es
     Dirichlet sobre los votos ya contados, **pero con el tamaño muestral
     descontado por el efecto de diseño**:

         p ~ Dirichlet(alpha + v_contados / deff)

     Ese `deff` es la pieza que trae la fase 03 y lo que impide tratar 100 mesas
     contadas como 100 observaciones independientes: en ERM 2022 valía 2.0–2.6
     para las listas grandes, así que 100 mesas informan como ~45.

  2. Los votos que faltan se reparten con esa propensión:

         v_faltantes ~ Multinomial(V_u, p)

     Sortear `p` una vez por simulación —y no por mesa— es lo que reproduce la
     correlación espacial: si el distrito resulta más favorable a una lista de lo
     que decía la muestra, lo es en **todas** las mesas que faltan a la vez.

  3. Resultado final = contados + faltantes. Repetido N veces da la distribución.

POR QUÉ EL DEFF Y NO OTRA COSA
------------------------------
Con `deff = 1` esto colapsa al muestreo aleatorio simple y las bandas salen
absurdamente estrechas: es el error clásico de tratar las actas como una muestra
al azar del electorado. El deff es la corrección, y está medido, no supuesto.

LO QUE ESTE MODELO **NO** CAPTURA
---------------------------------
Que las mesas que faltan no son una muestra aleatoria de las que faltan: llegan
tarde los locales remotos, y esos votan distinto. El sesgo de composición se
corrige aparte, con la distribución empírica de error de la fase 03, y solo se
puede estimar donde hay estructura de local. Aquí se asume intercambiabilidad
condicional a la propensión del distrito, que es optimista.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Prior débil por organización. Evita que una lista con cero votos en la muestra
# quede con probabilidad exactamente cero de aparecer en lo que falta.
ALPHA = 0.5


@dataclass
class Pronostico:
    orgs: tuple[str, ...]
    p_gana: dict[str, float]
    media: dict[str, float]
    p05: dict[str, float]
    p95: dict[str, float]
    pct_contado: float
    n_sims: int
    # Fracción de simulaciones en que el líder actual no gana. Es la medida
    # directa del riesgo de llamar la carrera ahora.
    riesgo_lider: float = 0.0
    empate_tecnico: bool = field(default=False)


def simula(votos_contados: dict[str, int], votos_faltantes: int,
           deff: float = 2.0, n_sims: int = 2000,
           rng: np.random.Generator | None = None) -> Pronostico:
    """Distribución del resultado final por Monte Carlo sobre lo que falta.

    `votos_contados` : votos por organización en las mesas ya contabilizadas.
    `votos_faltantes`: votos que se esperan de las mesas que faltan. Se estima
                       de los electores hábiles de esas mesas por la
                       participación observada, no de la nada.
    `deff`           : efecto de diseño de la carrera (fase 03). Descuenta el
                       tamaño muestral efectivo.
    """
    rng = rng or np.random.default_rng()
    orgs = tuple(votos_contados)
    v = np.array([votos_contados[o] for o in orgs], dtype=float)
    total_contado = v.sum()
    if total_contado <= 0 or len(orgs) < 2:
        return Pronostico(orgs, {o: float("nan") for o in orgs}, {}, {}, {},
                          0.0, 0)

    if votos_faltantes <= 0:
        # Nada que simular: el resultado es el que hay.
        share = v / total_contado
        ganador = orgs[int(v.argmax())]
        return Pronostico(
            orgs, {o: float(o == ganador) for o in orgs},
            dict(zip(orgs, share)), dict(zip(orgs, share)),
            dict(zip(orgs, share)), 1.0, 0, 0.0, False)

    # 1. Posterior de la propensión, con el tamaño muestral descontado.
    conc = v / max(deff, 1.0) + ALPHA
    p = rng.dirichlet(conc, size=n_sims)

    # 2. Los votos que faltan se reparten con esa propensión.
    faltan = np.empty((n_sims, len(orgs)), dtype=np.int64)
    for i in range(n_sims):
        faltan[i] = rng.multinomial(int(votos_faltantes), p[i])

    # 3. Resultado final por simulación.
    final = v[None, :] + faltan
    share = final / final.sum(axis=1, keepdims=True)
    gana = share.argmax(axis=1)
    cuenta = np.bincount(gana, minlength=len(orgs)) / n_sims

    lider_actual = int(v.argmax())
    total = total_contado + votos_faltantes
    return Pronostico(
        orgs=orgs,
        p_gana=dict(zip(orgs, cuenta)),
        media=dict(zip(orgs, share.mean(axis=0))),
        p05=dict(zip(orgs, np.quantile(share, 0.05, axis=0))),
        p95=dict(zip(orgs, np.quantile(share, 0.95, axis=0))),
        pct_contado=total_contado / total,
        n_sims=n_sims,
        riesgo_lider=1.0 - cuenta[lider_actual],
        # Nadie llega al umbral de llamada: la carrera está genuinamente abierta.
        empate_tecnico=bool(cuenta.max() < 0.995),
    )


def deff_de(p_lider: float, tabla=None) -> float:
    """Efecto de diseño según el nivel de participación del puntero.

    Valores medianos de ERM 2018 y 2022, que son los que rigen: hay un quiebre
    estructural entre 2014 y 2018 y los procesos viejos subestiman la varianza
    un 25–40%.
    """
    if p_lider < 0.05:
        return 1.21
    if p_lider < 0.15:
        return 1.68
    if p_lider < 0.30:
        return 2.03
    if p_lider < 0.50:
        return 2.25
    return 2.57


# ── Calibración contra el error medido ───────────────────────────────────────
# El `deff` a nivel de mesa captura la correlación espacial entre las mesas
# **contadas**, pero no el sesgo de composición de cuáles **faltan**: llegan
# tarde los locales remotos, que votan distinto. Por eso el modelo sale unas
# cuatro veces más confiado de lo que la realidad justifica.
#
# La corrección es fijar la dispersión contra la distribución de error empírica
# de la fase 03, que sí mide el fenómeno completo. Para una Dirichlet de
# concentración total C sobre una participación p, y con una fracción f de votos
# por llegar:
#
#     sd(share final) ~ f * sqrt( p(1-p) / (C+1) )
#
# Igualando a la sd observada a ese nivel de avance y despejando:
#
#     C = f^2 * p(1-p) / sd_objetivo^2  -  1
#
# Así la concentración deja de ser una propiedad del muestreo y pasa a ser el
# parámetro que hace que el modelo tenga **cobertura correcta**: que cuando diga
# 95%, acierte el 95% de las veces.

# sd del error (en puntos porcentuales) por fracción contabilizada. Medido sobre
# EG 2026 2V en `build_error_empirico.py`, distritos con 10+ mesas.
_SD_POR_AVANCE = [
    (0.05, 6.65), (0.10, 5.43), (0.20, 3.73), (0.30, 2.78), (0.40, 2.22),
    (0.50, 1.78), (0.60, 1.50), (0.75, 1.06), (0.90, 0.48), (0.95, 0.31),
    (1.00, 0.0),
]


def sd_objetivo(pct_contado: float) -> float:
    """sd esperada del error de la estimación cruda, en tanto por uno."""
    xs = [x for x, _ in _SD_POR_AVANCE]
    ys = [y / 100 for _, y in _SD_POR_AVANCE]
    return float(np.interp(min(max(pct_contado, 0.0), 1.0), xs, ys))


def concentracion_calibrada(p_lider: float, pct_contado: float,
                            votos_contados: float) -> float:
    """Concentración de la Dirichlet que reproduce el error observado."""
    f = max(1e-6, 1.0 - pct_contado)
    sd = max(sd_objetivo(pct_contado), 1e-6)
    c = (f ** 2) * p_lider * (1 - p_lider) / (sd ** 2) - 1.0
    # Nunca más informativa que la muestra efectiva, ni negativa.
    return float(min(max(c, 1.0), max(votos_contados, 1.0)))


def simula_calibrado(votos_contados: dict[str, int], votos_faltantes: int,
                     n_sims: int = 2000,
                     rng: np.random.Generator | None = None) -> Pronostico:
    """Como `simula`, pero con la dispersión calibrada contra el error medido.

    Es la versión que debe usar el pipeline: `simula` con `deff` sirve para
    comparar y para entender de dónde viene la incertidumbre, pero subestima.
    """
    rng = rng or np.random.default_rng()
    orgs = tuple(votos_contados)
    v = np.array([votos_contados[o] for o in orgs], dtype=float)
    tot_c = v.sum()
    if tot_c <= 0 or len(orgs) < 2:
        return Pronostico(orgs, {o: float("nan") for o in orgs}, {}, {}, {}, 0.0, 0)
    if votos_faltantes <= 0:
        return simula(votos_contados, 0, 1.0, n_sims, rng)

    pct = tot_c / (tot_c + votos_faltantes)
    p_lider = float(v.max() / tot_c)
    C = concentracion_calibrada(p_lider, pct, tot_c)
    # Se reparte la concentración según la composición observada.
    conc = (v / tot_c) * C + ALPHA
    p = rng.dirichlet(conc, size=n_sims)

    faltan = np.empty((n_sims, len(orgs)), dtype=np.int64)
    for i in range(n_sims):
        faltan[i] = rng.multinomial(int(votos_faltantes), p[i])
    final = v[None, :] + faltan
    share = final / final.sum(axis=1, keepdims=True)
    cuenta = np.bincount(share.argmax(axis=1), minlength=len(orgs)) / n_sims

    return Pronostico(
        orgs=orgs, p_gana=dict(zip(orgs, cuenta)),
        media=dict(zip(orgs, share.mean(axis=0))),
        p05=dict(zip(orgs, np.quantile(share, 0.05, axis=0))),
        p95=dict(zip(orgs, np.quantile(share, 0.95, axis=0))),
        pct_contado=pct, n_sims=n_sims,
        riesgo_lider=1.0 - cuenta[int(v.argmax())],
        empate_tecnico=bool(cuenta.max() < 0.995))


# ── Forecaster jerárquico: carreras cuya circunscripción son muchos distritos ─
# `simula_calibrado` agrupa todo lo contado en una sola Dirichlet. Para una
# carrera distrital eso está bien: lo que falta son mesas del mismo distrito.
#
# Para gobernador no. La circunscripción es el departamento y lo que falta son
# **distritos y provincias enteras sin una sola acta**. Agruparlo todo asume que
# lo ausente se parece a lo presente, y el error no es aleatorio: llegan tarde
# las provincias altoandinas, que votan distinto de la capital.
#
# El modelo estratifica por distrito. A los votos que faltan de un distrito que
# **sí** reportó se les aplica la composición observada de ese distrito; a los de
# un distrito que **no** reportó se les aplica la composición de su provincia —o
# del departamento, si la provincia tampoco reportó— más el ruido geográfico
# medido en `build_varianzas_geograficas.py`.
#
# La consecuencia práctica: mientras falte una provincia entera, la banda no se
# cierra por más actas que lleguen del resto. Que es exactamente como debe ser.

# sd de la participación de una unidad alrededor de la de su unidad padre,
# expresada como k * sqrt(p(1-p)) para que extrapole por encima del 50%.
# k mediano sobre ERM 2002-2022 (`varianzas_geograficas.parquet`).
_K_DIST_EN_PROV = [(0.0, 0.0), (0.025, 0.061), (0.10, 0.182), (0.225, 0.196),
                   (0.40, 0.195), (1.0, 0.195)]
_K_PROV_EN_DEP = [(0.0, 0.0), (0.025, 0.091), (0.10, 0.169), (0.225, 0.175),
                  (0.40, 0.162), (1.0, 0.162)]


def _sd_geo(p: np.ndarray, tabla) -> np.ndarray:
    """sd de la participación de la unidad hija, dado el nivel de la madre."""
    xs = [x for x, _ in tabla]
    ys = [y for _, y in tabla]
    k = np.interp(np.clip(p, 0.0, 1.0), xs, ys)
    return k * np.sqrt(np.clip(p * (1 - p), 0.0, None))


def _perturba(p: np.ndarray, sd: np.ndarray, rng) -> np.ndarray:
    """Perturba un vector de participaciones conservando el símplex.

    Ruido aditivo-logístico: se mueve cada componente en escala log y se
    renormaliza. Para una componente con participación p, un ruido de desvío s
    en escala log produce un desvío de aproximadamente p(1-p)*s en la
    participación, así que se elige s = sd_objetivo / (p(1-p)).
    """
    den = np.clip(p * (1 - p), 1e-6, None)
    s = np.clip(sd / den, 0.0, 4.0)
    q = np.log(np.clip(p, 1e-9, None)) + rng.normal(0.0, s)
    q = np.exp(q - q.max(axis=-1, keepdims=True))
    return q / q.sum(axis=-1, keepdims=True)


@dataclass
class PronosticoGobernador:
    orgs: tuple[str, ...]
    pct_contado: float
    n_sims: int
    # P(la organización gana en primera vuelta, es decir supera el 30%)
    p_gana_1v: dict[str, float]
    # P(la organización pasa a segunda vuelta)
    p_pasa_2v: dict[str, float]
    # P(la carrera se resuelve en segunda vuelta)
    p_segunda: float
    media: dict[str, float]
    p05: dict[str, float]
    p95: dict[str, float]
    # Escenario más probable y su probabilidad. ('1V', org) o ('2V', (a, b)).
    escenario: tuple
    p_escenario: float
    # Distritos de la circunscripción sin una sola acta contabilizada.
    distritos_sin_reportar: int


UMBRAL_1V = 0.30


def simula_gobernador(votos_por_distrito: np.ndarray,
                      totales_esperados: np.ndarray,
                      provincias: np.ndarray,
                      orgs: tuple[str, ...],
                      n_sims: int = 1000,
                      rng: np.random.Generator | None = None
                      ) -> PronosticoGobernador:
    """Proyección de una carrera de gobernador, estratificada por distrito.

    `votos_por_distrito` : matriz (D, K) de votos ya contabilizados.
    `totales_esperados`  : vector (D,) de votos válidos totales que se esperan
                           de cada distrito. En producción sale de electores
                           hábiles por la participación proyectada.
    `provincias`         : vector (D,) con el código de provincia de cada
                           distrito. Define el nivel intermedio de la jerarquía.
    """
    rng = rng or np.random.default_rng()
    V = np.asarray(votos_por_distrito, dtype=float)
    T = np.asarray(totales_esperados, dtype=float)
    D, K = V.shape
    contado_d = V.sum(axis=1)
    faltan_d = np.clip(T - contado_d, 0.0, None)
    tot_contado = contado_d.sum()
    if tot_contado <= 0 or K < 2:
        nan = {o: float("nan") for o in orgs}
        return PronosticoGobernador(orgs, 0.0, 0, nan, nan, float("nan"),
                                    nan, nan, nan, ("?", None), 0.0, D)

    reporto = contado_d > 0
    # Composición observada en cada nivel de la jerarquía.
    p_dep = V.sum(axis=0) / tot_contado
    provs = np.unique(provincias)
    p_prov = {}
    for pr in provs:
        m = (provincias == pr) & reporto
        if m.any() and V[m].sum() > 0:
            p_prov[pr] = V[m].sum(axis=0) / V[m].sum()

    sd_dist = _sd_geo(p_dep, _K_DIST_EN_PROV)
    sd_prov = _sd_geo(p_dep, _K_PROV_EN_DEP)

    # Error del promedio departamental. Las unidades independientes son las
    # **provincias**, no los distritos: cuando llega una provincia entera
    # reportan veinte distritos de golpe, pero todos comparten el efecto de
    # provincia, así que son una observación del departamento y no veinte.
    # Tratarlos como independientes es lo que produce llamadas tempranas
    # falsas —el modelo cree saber del departamento lo que solo sabe de una
    # provincia.
    #
    # Número efectivo de provincias observadas, con pesos de Kish sobre el voto
    # ya contabilizado:  n_ef = (sum w)^2 / sum w^2.
    peso_prov = np.array([contado_d[provincias == pr].sum() for pr in provs])
    w = peso_prov[peso_prov > 0]
    n_ef_prov = (w.sum() ** 2) / (w ** 2).sum() if len(w) else 1.0
    # Dentro de las provincias observadas queda el residuo de sus distritos.
    w_d = contado_d[reporto]
    n_ef_dist = ((w_d.sum() ** 2) / (w_d ** 2).sum()) if len(w_d) else 1.0
    sd_dep = np.sqrt(sd_prov ** 2 / max(n_ef_prov, 1.0)
                     + sd_dist ** 2 / max(n_ef_dist, 1.0))

    sd_ausente_total = np.sqrt(sd_prov ** 2 + sd_dist ** 2)

    # ── Vectorizado sobre simulaciones ───────────────────────────────────
    S = n_sims
    idx_prov = np.searchsorted(provs, provincias)
    hay_prov = np.array([pr in p_prov for pr in provs])
    mat_prov = np.zeros((len(provs), K))
    for j, pr in enumerate(provs):
        if hay_prov[j]:
            mat_prov[j] = p_prov[pr]

    # 1. Composición departamental verdadera.
    p_dep_s = _perturba(np.tile(p_dep, (S, 1)), sd_dep, rng)          # (S, K)
    # 2. Composición de cada provincia: la observada, o una simulada.
    p_prov_s = np.empty((S, len(provs), K))
    p_prov_s[:, hay_prov, :] = mat_prov[hay_prov][None, :, :]
    n_falta = int((~hay_prov).sum())
    if n_falta:
        base_f = np.repeat(p_dep_s[:, None, :], n_falta, axis=1)
        p_prov_s[:, ~hay_prov, :] = _perturba(base_f, sd_prov, rng)

    # 3. Composición de los votos que faltan en cada distrito.
    activos = np.where(faltan_d > 0)[0]
    q = np.empty((S, len(activos), K))
    rep = reporto[activos]

    ir = activos[rep]
    if len(ir):
        obs = V[ir] / contado_d[ir][:, None]
        pct_i = contado_d[ir] / np.clip(T[ir], 1.0, None)
        C = np.array([concentracion_calibrada(float(o.max()), float(pi), float(ci))
                      for o, pi, ci in zip(obs, pct_i, contado_d[ir])])
        alfa = obs * C[:, None] + ALPHA
        g = rng.gamma(np.broadcast_to(alfa, (S,) + alfa.shape))
        q[:, rep, :] = g / g.sum(axis=2, keepdims=True)

    ia = activos[~rep]
    if len(ia):
        pj = idx_prov[ia]
        tiene = hay_prov[pj]
        base_a = p_prov_s[:, pj, :]
        sd_a = np.where(tiene[:, None], sd_dist[None, :], sd_ausente_total[None, :])
        q[:, ~rep, :] = _perturba(base_a, np.broadcast_to(sd_a, (S,) + sd_a.shape), rng)

    # 4. Reparto de los votos faltantes. El ruido multinomial se aproxima con su
    #    normal: a estos tamaños es un orden de magnitud menor que el geográfico.
    f = faltan_d[activos][None, :, None]
    esp = f * q
    ruido = rng.normal(0.0, np.sqrt(np.clip(f * q * (1 - q), 0.0, None)))
    add = np.clip(esp + ruido, 0.0, None)
    total_final = V.sum(axis=0)[None, :] + add.sum(axis=1)

    share = total_final / total_final.sum(axis=1, keepdims=True)
    ordenado = np.argsort(-total_final, axis=1)
    primero = ordenado[:, 0]
    segundo = ordenado[:, 1]
    gana_1v = share[np.arange(n_sims), primero] >= UMBRAL_1V

    p_gana = {o: 0.0 for o in orgs}
    p_pasa = {o: 0.0 for o in orgs}
    escenarios: dict[tuple, int] = {}
    for s in range(n_sims):
        a, b = orgs[primero[s]], orgs[segundo[s]]
        if gana_1v[s]:
            p_gana[a] += 1.0 / n_sims
            e = ("1V", a)
        else:
            p_pasa[a] += 1.0 / n_sims
            p_pasa[b] += 1.0 / n_sims
            e = ("2V", tuple(sorted((a, b))))
        escenarios[e] = escenarios.get(e, 0) + 1
    mejor, cuenta = max(escenarios.items(), key=lambda kv: kv[1])

    return PronosticoGobernador(
        orgs=orgs,
        pct_contado=float(tot_contado / max(T.sum(), 1.0)),
        n_sims=n_sims,
        p_gana_1v=p_gana,
        p_pasa_2v=p_pasa,
        p_segunda=float(1.0 - gana_1v.mean()),
        media=dict(zip(orgs, share.mean(axis=0))),
        p05=dict(zip(orgs, np.quantile(share, 0.05, axis=0))),
        p95=dict(zip(orgs, np.quantile(share, 0.95, axis=0))),
        escenario=mejor,
        p_escenario=cuenta / n_sims,
        distritos_sin_reportar=int((~reporto).sum()),
    )
