#!/usr/bin/env python3
"""435 distritos uninominales para la Cámara de Diputados, a la estadounidense.

1. Reparto: el extranjero recibe escaños según su parte de los votos válidos
   (vota mucho menos de lo que pesa en el padrón); los demás se reparten con
   Huntington-Hill (el método de la Cámara de EE.UU.) entre las 26
   circunscripciones del territorio, por electores hábiles, mínimo uno.

2. Trazado: bisección recursiva sobre el grafo de vecindad de las celdas de
   los locales de votación (02_celdas.py: dos locales son vecinos si sus celdas
   comparten borde en el mapa). Para partir n escaños en ⌊n/2⌋ y ⌈n/2⌉:
     - se arman árboles de expansión mínima con pesos = distancia × costo del
       límite (mismo distrito 1, otro distrito 4, otra provincia 16) × ruido;
     - en cada árbol se busca la arista cuyo corte deja la mitad más cerca
       del objetivo; cortar un árbol garantiza que **las dos mitades son
       contiguas**;
     - el resto (lo que un local entero no alcanza a cuadrar) se ajusta
       pasando mesas de un local de la frontera al otro lado;
     - de todos los árboles se queda el corte que parte menos distritos y
       provincias y, a igualdad, el más compacto.
   En el extranjero no hay coordenadas: se corta en una dimensión, en orden de
   continente → país → ciudad.

Neutral (no mira votos) y reproducible (semilla fija).

Uso:
    uv run --with pandas --with pyarrow --with scipy python scripts/03_distritos.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order, minimum_spanning_tree

AQUI = Path(__file__).resolve().parents[1]
DATAPOL = AQUI.parents[1]
FUERA = []                              # cortes que no cuadraron en la tolerancia
COSTO = {0: 1.0, 1: 4.0, 2: 16.0}      # mismo distrito, otro distrito, otra provincia


def huntington_hill(pob: pd.Series, total: int) -> pd.Series:
    s = pd.Series(1, index=pob.index)
    while s.sum() < total:
        s[(pob / np.sqrt(s * (s + 1))).idxmax()] += 1
    return s


class Grafo:
    """Nodos = locales (o pedazos de local tras repartir mesas)."""

    def __init__(self, nodos: pd.DataFrame, aristas: np.ndarray):
        self.n = nodos                     # x, y, pob, prov, dist, mesas(list)
        self.e = aristas                   # (k, 2) índices de nodos

    def vecinos_sub(self, sel: np.ndarray):
        en = np.zeros(len(self.n), bool)
        en[sel] = True
        e = self.e[en[self.e[:, 0]] & en[self.e[:, 1]]]
        return e


def arbol_y_corte(G, sel, e, objetivo, rng, P):
    """Un árbol aleatorio sobre `sel` y su mejor arista de corte."""
    pos = {v: i for i, v in enumerate(sel)}
    N = G.n
    a = np.array([pos[x] for x in e[:, 0]])
    b = np.array([pos[x] for x in e[:, 1]])
    x, y = N.x.to_numpy()[sel], N.y.to_numpy()[sel]
    dist = np.hypot(x[a] - x[b], y[a] - y[b]) + 1e-3
    prov, dis = N.prov.to_numpy()[sel], N.dist.to_numpy()[sel]
    nivel = np.where(prov[a] != prov[b], 2, np.where(dis[a] != dis[b], 1, 0))
    w = dist * np.vectorize(COSTO.get)(nivel) * rng.uniform(1, 2.5, len(a))
    M = coo_matrix((w, (a, b)), shape=(len(sel), len(sel)))
    T = minimum_spanning_tree(M + M.T).tocsr()
    T = T + T.T
    orden, padre = breadth_first_order(T, 0, directed=False, return_predecessors=True)
    if len(orden) < len(sel):
        return None                         # grafo no conexo
    pob = N.pob.to_numpy()[sel].astype(float)
    sub = pob.copy()
    for v in orden[::-1]:
        if padre[v] >= 0:
            sub[padre[v]] += sub[v]
    # Cortar la arista (v, padre v) deja `sub[v]` de un lado.
    dev = np.minimum(np.abs(sub - objetivo), np.abs(P - sub - objetivo))
    dev[orden[0]] = np.inf
    v = int(np.argmin(dev))
    lado = np.zeros(len(sel), bool)       # True = subárbol de v
    hijos = [[] for _ in range(len(sel))]
    for u in orden[1:]:
        hijos[padre[u]].append(u)
    pila = [v]
    while pila:
        u = pila.pop()
        lado[u] = True
        pila += hijos[u]
    if abs(sub[v] - objetivo) > abs(P - sub[v] - objetivo):
        lado = ~lado
    return lado, (a, b), T


def _parte(G, v, k, ancla):
    """Separa las primeras k mesas del nodo v en un nodo nuevo, colgado de `ancla`.

    El pedazo no tiene área en el mapa (la celda se dibuja con el resto del
    local), así que entra al grafo como hoja: una sola arista, hacia un vecino
    del otro lado. Nunca puede ser puente de un distrito."""
    N = G.n.copy()          # nunca editar en sitio: biseca guarda fotos del grafo
    fila = N.iloc[v]
    mov = dict(fila)
    mov["mesas"], mov["pob_mesas"] = fila.mesas[:k], fila.pob_mesas[:k]
    mov["pob"] = float(sum(mov["pob_mesas"]))
    mov["pieza"] = True
    N.at[N.index[v], "mesas"] = fila.mesas[k:]
    N.at[N.index[v], "pob_mesas"] = fila.pob_mesas[k:]
    N.at[N.index[v], "pob"] = float(sum(fila.pob_mesas[k:]))
    nuevo = len(N)
    G.n = pd.concat([N, pd.DataFrame([mov])], ignore_index=True)
    G.e = np.vstack([G.e, [[ancla, nuevo]]])
    return nuevo


def _sigue_conexo(sel, cede, a, b, c):
    """¿El lado que cede sigue conexo si se le quita el nodo c?"""
    from scipy.sparse.csgraph import connected_components
    resto = cede.copy()
    resto[c] = False
    idx = np.where(resto)[0]
    if len(idx) == 0:
        return False
    pos = -np.ones(len(sel), int)
    pos[idx] = np.arange(len(idx))
    m = resto[a] & resto[b]
    M = coo_matrix((np.ones(m.sum()), (pos[a[m]], pos[b[m]])), shape=(len(idx),) * 2)
    return connected_components(M, directed=False)[0] == 1


def ajusta(G, sel, lado, objetivo, tol_abs, max_pasos=200):
    """Pasa mesas de locales fronterizos al otro lado hasta cuadrar el objetivo.

    Un local cede todas sus mesas si el lado que cede sigue conexo sin él; si
    no, a lo sumo la mitad. Devuelve lo mejor que alcanzó y su desvío; modifica G."""
    sel, lado = sel.copy(), lado.copy()
    for _ in range(max_pasos):
        pob = G.n.pob.to_numpy()[sel]
        resto = objetivo - pob[lado].sum()        # >0: a la mitad le falta
        if abs(resto) <= tol_abs:
            break
        cede = ~lado if resto > 0 else lado
        e = G.vecinos_sub(sel)
        pos = {v: i for i, v in enumerate(sel)}
        a = np.array([pos[x] for x in e[:, 0]])
        b = np.array([pos[x] for x in e[:, 1]])
        fr = lado[a] != lado[b]
        pieza = G.n.pieza.to_numpy()[sel]
        cand = [c for c in np.unique(np.concatenate([a[fr], b[fr]])) if cede[c] and not pieza[c]]
        mejor = None
        for c in cand:
            pm = G.n.pob_mesas.iloc[sel[c]]
            cum = np.cumsum(pm)
            # El local entero si el lado que cede sigue conexo sin él; si no, a lo
            # sumo la mitad de sus mesas (la celda se dibuja con la mayoría).
            entero = _sigue_conexo(sel, cede, a, b, c)
            ks = list(range(1, len(pm) // 2 + 1)) + ([len(pm)] if entero else [])
            if not ks:
                continue
            cum = cum[np.array(ks) - 1]
            i = int(np.argmin(np.abs(cum - abs(resto))))
            err = abs(cum[i] - abs(resto))
            if mejor is None or err < mejor[0]:
                mejor = (err, c, ks[i], len(pm))
        if mejor is None:
            break
        _, c, k, total = mejor
        if k == total:
            lado[c] = not lado[c]                 # pasa el local entero
            continue
        otro = np.concatenate([b[(a == c) & fr], a[(b == c) & fr]])
        nuevo = _parte(G, sel[c], k, sel[otro[0]])
        sel = np.append(sel, nuevo)
        lado = np.append(lado, not lado[c])        # el pedazo, al otro lado de su local
    return sel, lado, abs(objetivo - G.n.pob.to_numpy()[sel][lado].sum())


def biseca(G, sel, n, tol, rng, intentos):
    a_esc = n // 2
    pob = G.n.pob.to_numpy()[sel]
    P = pob.sum()
    objetivo = P * a_esc / n
    tol_abs = tol * P / n
    e = G.vecinos_sub(sel)
    mejores = []
    for _ in range(intentos):
        r = arbol_y_corte(G, sel, e, objetivo, rng, P)
        if r is None:
            break
        lado, ab, _ = r
        dev = abs(pob[lado].sum() - objetivo)
        N = G.n
        dis = N.dist.to_numpy()[sel]
        prov = N.prov.to_numpy()[sel]
        partidos_d = len(set(dis[lado]) & set(dis[~lado]))
        partidos_p = len(set(prov[lado]) & set(prov[~lado]))
        X = np.column_stack([N.x.to_numpy()[sel], N.y.to_numpy()[sel]])
        iner = sum((pob[g, None] * (X[g] - np.average(X[g], axis=0, weights=pob[g])) ** 2).sum()
                   for g in (lado, ~lado))
        mejores.append((dev, partidos_p, partidos_d, iner, lado, ab))
    if not mejores:
        raise RuntimeError("grafo no conexo")
    imin = min(m[3] for m in mejores)
    # Puntaje: límites administrativos respetados, compacidad, y cuánto hay que
    # ajustar con mesas (cada local partido es un costo).
    def puntaje(m):
        dev, pp, pd_, iner, *_ = m
        return 3 * pp + pd_ + 2.0 * (iner / imin - 1) + (0 if dev <= tol_abs else 0.5)
    mejor = None
    cuota = P / n
    for m in sorted(mejores, key=lambda m: (m[0] > cuota, puntaje(m))):
        dev, _, _, _, lado, ab = m
        if dev <= tol_abs:
            return sel, lado
        foto = (G.n.copy(), G.e.copy())
        s2, l2, d2 = ajusta(G, sel, lado, objetivo, tol_abs)
        if mejor is None or d2 < mejor[0]:
            mejor = (d2, s2, l2, G.n, G.e)
        if d2 <= tol_abs:
            return s2, l2
        G.n, G.e = foto
    d2, s2, l2, G.n, G.e = mejor
    FUERA.append((n, P, d2, tol_abs))
    return s2, l2


def grafo_circ(df: pd.DataFrame, celdas: pd.DataFrame, vecinos: pd.DataFrame) -> Grafo:
    """Grafo de locales de la circunscripción con la vecindad del mapa.

    Si queda partido (un local geocodificado en el polígono de otra región, una
    isla), cada componente suelta se une a la más cercana por su par de locales
    más próximo: es la única arista que no viene del mapa."""
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    loc = df.groupby("local").agg(lon=("lon", "first"), lat=("lat", "first"),
                                  pob=("electores", "sum"),
                                  mesas=("codigo_mesa", list),
                                  pob_mesas=("electores", list)).reset_index()
    ub = celdas.set_index("local").ubigeo_poligono
    loc["dist"] = loc.local.map(ub).fillna(df.groupby("local").ubigeo.first().reindex(loc.local).reset_index(drop=True))
    loc["prov"] = loc.dist.str[:4]
    lat0 = np.deg2rad(loc.lat.mean())
    loc["x"] = loc.lon * np.cos(lat0) * 111.32
    loc["y"] = loc.lat * 111.32
    loc["pob"] = loc.pob.astype(float)
    loc["pieza"] = False
    pos = pd.Series(np.arange(len(loc)), index=loc.local)
    v = vecinos[vecinos.local_a.isin(pos.index) & vecinos.local_b.isin(pos.index)]
    e = np.column_stack([pos[v.local_a].to_numpy(), pos[v.local_b].to_numpy()]).astype(int) \
        if len(v) else np.zeros((0, 2), int)
    while True:
        M = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(loc),) * 2)
        k, lab = connected_components(M, directed=False)
        if k == 1:
            break
        grande = np.bincount(lab, weights=loc.pob).argmax()
        X = loc[["x", "y"]].to_numpy()
        principal = np.where(lab == grande)[0]
        resto = np.where(lab != grande)[0]
        d, ii = cKDTree(X[principal]).query(X[resto])
        r = int(np.argmin(d))
        e = np.vstack([e, [[resto[r], principal[ii[r]]]]])
    return Grafo(loc, e)


def distrita_mapa(df, n, tol, prefijo, celdas, vecinos, semilla, intentos):
    G = grafo_circ(df, celdas, vecinos)
    rng = np.random.default_rng(semilla)
    hojas = []

    def rec(sel, n, et):
        if n == 1:
            hojas.append((et, sel))
            return
        sel, lado = biseca(G, sel, n, tol, rng, intentos)
        rec(sel[lado], n // 2, et + "0")
        rec(sel[~lado], n - n // 2, et + "1")

    rec(np.arange(len(G.n)), n, "")
    filas, celda = [], {}
    for et, sel in hojas:
        for v in sel:
            for mesa in G.n.mesas.iloc[v]:
                filas.append((mesa, et))
            if not G.n.pieza.iloc[v]:
                celda[G.n.local.iloc[v]] = et
    asig = pd.DataFrame(filas, columns=["codigo_mesa", "_e"])
    lat = df.set_index("codigo_mesa").lat
    orden = asig.assign(lat=asig.codigo_mesa.map(lat)).groupby("_e").lat.mean() \
        .sort_values(ascending=False).index
    mapa = {e: f"{prefijo}-{i + 1:02d}" for i, e in enumerate(orden)}
    return asig.set_index("codigo_mesa")._e.map(mapa), {k: mapa[v] for k, v in celda.items()}


def distrita_lineal(df, n, tol, prefijo):
    """PEX: corte en una dimensión, ciudad por ciudad."""
    d = df.sort_values(["ubigeo", "local", "codigo_mesa"])
    w = d.electores.to_numpy(float)
    nivel = np.full(len(d) - 1, 2)
    nivel[d.local.to_numpy()[1:] != d.local.to_numpy()[:-1]] = 1
    nivel[d.ubigeo.to_numpy()[1:] != d.ubigeo.to_numpy()[:-1]] = 0
    asig = np.empty(len(d), object)

    def rec(lo, hi, n, et):
        if n == 1:
            asig[lo:hi] = et
            return
        P = w[lo:hi].sum()
        obj = P * (n // 2) / n
        cum = np.cumsum(w[lo:hi])[:-1]
        err = np.abs(cum - obj)
        ok = err <= tol * P / n
        lv = np.where(ok, nivel[lo:hi - 1], 9)
        cand = np.where(lv == lv.min())[0] if ok.any() else [int(np.argmin(err))]
        i = lo + cand[np.argmin(err[cand])] + 1
        rec(lo, i, n // 2, et + "0")
        rec(i, hi, n - n // 2, et + "1")

    rec(0, len(d), n, "")
    orden = list(dict.fromkeys(asig))
    mapa = {e: f"{prefijo}-{i + 1:02d}" for i, e in enumerate(orden)}
    return pd.Series([mapa[x] for x in asig], index=d.codigo_mesa.to_numpy())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mesas", type=Path, default=AQUI / "data/mesas.parquet")
    ap.add_argument("--escanos", type=int, default=435)
    ap.add_argument("--validos", type=Path,
                    default=DATAPOL / "peru/2026eg/primera/data/results/peru_2026eg_mesa_primera.csv",
                    help="votos válidos por mesa, para los escaños del extranjero")
    ap.add_argument("--tol", type=float, default=0.005,
                    help="tolerancia por corte, como fracción de la cuota por escaño")
    ap.add_argument("--intentos", type=int, default=60, help="árboles por corte")
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=AQUI / "data")
    a = ap.parse_args()

    m = pd.read_parquet(a.mesas).sort_values("codigo_mesa").reset_index(drop=True)
    pob = m.groupby("circ").electores.sum().sort_values(ascending=False)
    # El extranjero vota mucho menos que lo que pesa en el padrón: sus escaños
    # salen de su parte de los votos válidos; el resto se reparte en el territorio
    # nacional por electores, con Huntington-Hill.
    val = pd.read_csv(a.validos, usecols=["codigo_mesa", "votos_validos"])
    val["codigo_mesa"] = val.codigo_mesa.astype(str).str.zfill(6)
    v = m.merge(val, on="codigo_mesa").groupby("exterior").votos_validos.sum()
    pex = "PERUANOS EN EL EXTRANJERO"
    n_pex = max(1, int(round(a.escanos * v[True] / v.sum())))
    esc = pd.concat([huntington_hill(pob.drop(pex), a.escanos - n_pex), pd.Series({pex: n_pex})])
    esc = esc.reindex(pob.index)
    print(f"PEX: {v[True] / v.sum():.2%} de los votos válidos → {n_pex} escaños; "
          f"territorio nacional: {a.escanos - n_pex}")
    rep = pd.DataFrame({"electores": pob, "escanos": esc})
    rep["cuota"] = (rep.electores / rep.escanos).round(0)
    rep.index.name = "circ"
    rep.to_csv(a.out / "reparto.csv")

    celdas = pd.read_parquet(a.out / "celdas.parquet", columns=["local", "ubigeo_poligono"])
    vecinos = pd.read_parquet(a.out / "vecinos.parquet")

    partes, celdas_us = [], {}
    for i, (circ, n) in enumerate(esc.items()):
        df = m[m.circ == circ]
        pref = f"{i + 1:02d}"
        if df.lat.isna().any():
            s = distrita_lineal(df, int(n), a.tol, pref)
        else:
            # Los desvíos de cada corte se suman: si algún distrito sale de ±1%,
            # se vuelve a trazar con otra semilla.
            cuota = df.electores.sum() / int(n)
            for intento in range(12):
                s, cu = distrita_mapa(df, int(n), a.tol, pref, celdas, vecinos,
                                      a.semilla + i + 1000 * intento, a.intentos)
                pob_d = df.set_index("codigo_mesa").electores.groupby(s).sum()
                if (pob_d / cuota - 1).abs().max() <= 0.01:
                    break
            celdas_us.update(cu)
        partes.append(s)
        print(f"  {circ:28s} {int(n):3d} escaños", flush=True)
    m["distrito_us"] = m.codigo_mesa.map(pd.concat(partes))
    assert m.distrito_us.notna().all()
    m[["codigo_mesa", "distrito_us"]].to_parquet(a.out / "asignacion.parquet", index=False)
    # Para el mapa: cada celda va con el resto de su local (no con sus pedazos).
    pd.Series(celdas_us, name="distrito_us").rename_axis("local").reset_index() \
        .to_parquet(a.out / "celda_distrito.parquet", index=False)

    d = m.groupby(["circ", "distrito_us"]).agg(electores=("electores", "sum"),
                                               n_distritos=("ubigeo", "nunique"),
                                               n_locales=("local", "nunique"),
                                               mesas=("codigo_mesa", "size")).reset_index()
    d["cuota"] = d.circ.map(rep.cuota)
    d["desv"] = d.electores / d.cuota - 1
    nac = ~d.circ.eq("PERUANOS EN EL EXTRANJERO")
    cuota_nac = d.loc[nac, "electores"].sum() / nac.sum()
    d["desv_nacional"] = d.electores / cuota_nac - 1
    d.to_csv(a.out / "distritos_us.csv", index=False)

    if FUERA:
        print(f"AVISO: {len(FUERA)} cortes no entraron en la tolerancia (contigüidad primero): "
              + "; ".join(f"n={n} desvío {d:,.0f} > {t:,.0f}" for n, _, d, t in FUERA))
    partidos_dist = (m.groupby("ubigeo").distrito_us.nunique() > 1).sum()
    partidos_prov = (m[~m.exterior].groupby("prov").distrito_us.nunique() > 1).sum()
    partidos_loc = (m.groupby(["ubigeo", "local"]).distrito_us.nunique() > 1).sum()
    print(f"\n{len(d)} distritos · desviación vs. cuota de su circunscripción: "
          f"máx {d.desv.abs().max():.2%} · media |desv| {d.desv.abs().mean():.2%} · "
          f"{(d.desv.abs() <= 0.01).mean():.0%} dentro de ±1%")
    print(f"desviación vs. cuota del territorio ({cuota_nac:,.0f}): "
          f"mín {d.loc[nac, 'desv_nacional'].min():+.1%} máx {d.loc[nac, 'desv_nacional'].max():+.1%}")
    print(f"partidos: {partidos_dist} distritos administrativos de {m.ubigeo.nunique()} · "
          f"{partidos_prov} provincias · {partidos_loc} locales (por mesas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
