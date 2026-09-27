#!/usr/bin/env python3
"""Puntos ideales por cámara, línea oficialismo/oposición y métricas por miembro.

Método (heredado de congressional_votes_parsing/estimate_ideal_points.py, ver
su docstring para la justificación completa): embedding espectral de la
matriz de acuerdo **normalizada por filas**, siguiendo a Golub & Jackson. El
primer autovector de T = D⁻¹A es constante (autovalor 1) y se descarta solo;
los autovectores 2 y 3 son las coordenadas, y λ₂ es un índice de polarización
(≈0 consenso rápido, →1 dos bloques casi desconectados). Robustez contra MDS
clásico y PCA del voto; ajuste por clasificación correcta en 1D y 2D.

Novedades 2026:
* Filtros adaptados a pocas votaciones: se descartan las «unánimes» (minoría
  < max(3, 2.5% de los votos emitidos)) y los miembros con menos de
  max(5, 50% de las votaciones que quedan) votos emitidos.
* Signo: dim 1 orientada para que el oficialismo (config.OFICIALISMO) quede
  en positivo; dim 2 para que la bancada de oposición más grande quede en
  positivo. Es una convención de etiquetas.
* Línea oficialismo/oposición: el separador lineal en 2D que mejor divide a
  los miembros de un bloque y otro (barrido de direcciones y cortes;
  desempate por margen). La distancia a esa línea define a los «bisagra»; los
  que caen del lado del otro bloque son «cruzados».

Salida: data/modelo_<camara>.json
Run: python3 estimate.py [--camara senado]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import linalg
from scipy.stats import pearsonr, spearmanr

from config import OFICIALISMO, OPOSICION

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
EMITIDOS = ("SI", "NO", "ABS")
AUSENCIAS = ("AUS", "LIC", "SUS", "SINRES")


# ── diagnósticos (idénticos a 2021) ──────────────────────────────────────────

def best_cut_correct(coord: np.ndarray, is_si: np.ndarray) -> int:
    order = np.argsort(coord)
    s = is_si[order].astype(int)
    n = len(s)
    si_left = np.concatenate([[0], np.cumsum(s)])
    no_left = np.arange(n + 1) - si_left
    tot = si_left[-1]
    return int(max((no_left + tot - si_left).max(), (si_left + (n - tot) - no_left).max()))


def classification(coords: np.ndarray, V: pd.DataFrame, angles: int = 36) -> dict:
    total = c1 = c2 = base = 0
    for vid in V.columns:
        col = V[vid]
        mask = col.isin(["SI", "NO"]).to_numpy()
        if mask.sum() < 2:
            continue
        is_si = (col[mask] == "SI").to_numpy()
        xy = coords[mask]
        n = int(mask.sum())
        total += n
        base += min(is_si.sum(), n - is_si.sum())
        c1 += best_cut_correct(xy[:, 0], is_si)
        c2 += max(best_cut_correct(xy[:, 0] * np.cos(t) + xy[:, 1] * np.sin(t), is_si)
                  for t in np.linspace(0, np.pi, angles, endpoint=False))
    if not total:
        return {}
    return {"clasif_1d": c1 / total, "clasif_2d": c2 / total,
            "ganancia_dim2": (c2 - c1) / total,
            "pre_1d": (base - (total - c1)) / base if base else None}


def torgerson(A: np.ndarray) -> np.ndarray:
    n = A.shape[0]
    J = np.eye(n) - np.ones((n, n)) / n
    w, U = linalg.eigh(-0.5 * J @ ((1 - A) ** 2) @ J)
    o = np.argsort(w)[::-1]
    return U[:, o[:2]] * np.sqrt(np.maximum(w[o[:2]], 0))


def vote_pca(V: pd.DataFrame) -> np.ndarray:
    M = V.apply(lambda c: c.map({"SI": 1.0, "NO": -1.0, "ABS": 0.0}))
    M = M.apply(lambda c: c.fillna(c.mean()), axis=0).fillna(0)
    X = M.to_numpy() - M.to_numpy().mean(axis=0, keepdims=True)
    U, s, _ = np.linalg.svd(X, full_matrices=False)
    return U[:, :2] * s[:2]


def sp(a, b) -> float:
    r = spearmanr(a, b)[0]
    return float(abs(r)) if np.isfinite(r) else float("nan")


# ── línea oficialismo / oposición ────────────────────────────────────────────

def cutline(xy: np.ndarray, is_ofi: np.ndarray, angles: int = 180) -> dict:
    """Mejor separador lineal entre bloques: dirección θ y corte c tales que
    proj = x·cosθ + y·sinθ > c ⇒ oficialismo. Minimiza miembros mal
    clasificados; entre empates, maximiza el margen del corte."""
    best = None
    for t in np.linspace(0, 2 * np.pi, angles, endpoint=False):
        proj = xy[:, 0] * np.cos(t) + xy[:, 1] * np.sin(t)
        o = np.argsort(proj)
        ps, lab = proj[o], is_ofi[o]
        # corte entre ps[k-1] y ps[k]: izquierda = oposición, derecha = oficialismo
        ofi_left = np.concatenate([[0], np.cumsum(lab)])
        opo_right = np.concatenate([[0], np.cumsum((~lab)[::-1])])[::-1]
        errors = ofi_left + opo_right
        for k in np.flatnonzero(errors == errors.min()):
            lo = ps[k - 1] if k > 0 else ps[0] - 1
            hi = ps[k] if k < len(ps) else ps[-1] + 1
            cand = (int(errors[k]), -(hi - lo), float(t), float((lo + hi) / 2))
            if best is None or cand[:2] < best[:2]:
                best = cand
    err, neg_margin, t, c = best
    return {"theta": t, "c": c, "errores": err, "margen": -neg_margin,
            "nx": float(np.cos(t)), "ny": float(np.sin(t))}


# ── por cámara ───────────────────────────────────────────────────────────────

def estimate(camara: str, votos: pd.DataFrame, roster: list[dict], paginas: pd.DataFrame) -> dict:
    d = votos[votos.camara == camara].copy()
    miembros = {m["id"]: m for m in roster if m["camara"] == camara}
    V_all = d.pivot_table(index="miembro_id", columns="vote_id", values="voto",
                          aggfunc="first")
    n_vot = V_all.shape[1]

    # filtros
    cast = V_all.where(V_all.isin(EMITIDOS))
    n_cast = cast.notna().sum()
    si, no = (cast == "SI").sum(), (cast == "NO").sum()
    minority = np.minimum(si, no) + (cast == "ABS").sum() * 0   # ABS no cuenta como minoría
    keep_v = minority[minority >= np.maximum(3, 0.025 * n_cast)].index
    V = cast[keep_v]
    min_cast = max(5, int(0.5 * len(keep_v)))
    per_leg = V.notna().sum(axis=1)
    keep_l = per_leg[per_leg >= min_cast].index
    V = V.loc[keep_l]
    out = {"camara": camara, "n_votaciones": n_vot, "n_disputadas": len(keep_v),
           "min_votos_miembro": min_cast, "n_miembros_modelo": len(keep_l)}
    print(f"[{camara}] {n_vot} votaciones → {len(keep_v)} disputadas; "
          f"{len(keep_l)}/{V_all.shape[0]} miembros con ≥{min_cast} votos")

    coords = {}
    if len(keep_v) >= 3 and len(keep_l) >= 10:
        codes = np.full(V.shape, -1, dtype=np.int8)
        for k, lab in enumerate(EMITIDOS):
            codes[(V == lab).to_numpy()] = k
        n = codes.shape[0]
        A = np.full((n, n), np.nan)
        for i in range(n):
            both = (codes[i] >= 0) & (codes >= 0)
            p = both.sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                A[i] = ((codes[i] == codes) & both).sum(axis=1) / p
            A[i, p < 3] = np.nan
        np.fill_diagonal(A, 1.0)
        off = ~np.eye(n, dtype=bool)
        imput = int(np.isnan(A[off]).sum())
        A[np.isnan(A)] = np.nanmean(A[off])
        A = (A + A.T) / 2
        A = np.maximum(A, 1e-3)   # filas sin ceros: T bien definida

        dg = A.sum(axis=1)
        dis = dg ** -0.5
        w, U = linalg.eigh((A * dis[:, None]) * dis[None, :])
        o = np.argsort(w)[::-1]
        w, U = w[o], U[:, o]
        Vec = U * dis[:, None]
        X = (Vec[:, 1] - Vec[:, 1].mean()) / Vec[:, 1].std()
        Y = (Vec[:, 2] - Vec[:, 2].mean()) / Vec[:, 2].std()

        grupos = pd.Series({i: miembros[i]["grupo"] for i in V.index})
        ofi = grupos.isin(OFICIALISMO).to_numpy()
        if ofi.any() and X[ofi].mean() < 0:
            X = -X
        opo_big = grupos[grupos.isin(OPOSICION)].value_counts()
        if len(opo_big):
            sel = (grupos == opo_big.index[0]).to_numpy()
            if Y[sel].mean() < 0:
                Y = -Y
        xy = np.column_stack([X, Y])

        mds, pca = torgerson(A), vote_pca(V)
        out.update({
            "lambda2": float(w[1]), "lambda3": float(w[2]),
            "celdas_imputadas_pct": 100 * imput / off.sum(),
            "robustez_mds": sp(X, mds[:, 0]), "robustez_pca": sp(X, pca[:, 0]),
            **classification(xy, V),
        })
        coords = {mid: (float(x), float(y)) for mid, x, y in zip(V.index, X, Y)}

        blo = grupos.isin(OFICIALISMO | OPOSICION).to_numpy()
        # Si la dim 2 no se gana su lugar (< 2 pp de clasificación), la línea
        # es vertical sobre la dim 1: un separador 2D aprovecharía ruido y
        # pondría como «bisagras» a gente que está en un extremo del eje
        # principal (pasó con JP en el Senado con 14 votaciones).
        dos_d = out.get("ganancia_dim2", 0) >= 0.02
        cl = (cutline(xy[blo], ofi[blo]) if dos_d else
              cutline(np.column_stack([X, np.zeros_like(X)])[blo], ofi[blo], angles=1))
        cl["modo"] = "2d" if dos_d else "1d"
        out["linea"] = cl
        dist = xy @ np.array([cl["nx"], cl["ny"]]) - cl["c"]
        for mid, dd in zip(V.index, dist):
            coords[mid] += (float(dd),)
    else:
        print(f"  ⚠ [{camara}] muy pocos datos para estimar posiciones todavía")

    # métricas por miembro sobre TODAS las votaciones
    mayoria_bancada, mayoria_ofi = {}, {}
    for vid in V_all.columns:
        col = V_all[vid]
        g = pd.Series({i: miembros[i]["grupo"] for i in col.index if i in miembros})
        c = col[col.isin(EMITIDOS)]
        for grp in g.unique():
            cc = c[g.reindex(c.index) == grp]
            if len(cc):
                mayoria_bancada[(vid, grp)] = cc.value_counts().idxmax()
        co = c[g.reindex(c.index).isin(OFICIALISMO)]
        if len(co):
            mayoria_ofi[vid] = co.value_counts().idxmax()

    filas = []
    for mid, m in miembros.items():
        row = V_all.loc[mid] if mid in V_all.index else pd.Series(dtype=object)
        present = row.dropna()
        emit = present[present.isin(EMITIDOS)]
        leal = [v == mayoria_bancada.get((vid, m["grupo"])) for vid, v in emit.items()]
        conofi = [v == mayoria_ofi.get(vid) for vid, v in emit.items() if vid in mayoria_ofi]
        c = coords.get(mid)
        filas.append({
            "id": mid, "x": c[0] if c else None, "y": c[1] if c else None,
            "dist_linea": c[2] if c and len(c) > 2 else None,
            "n_emitidos": int(len(emit)), "n_registrado": int(len(present)),
            "asistencia": (float((~present.isin(AUSENCIAS)).mean()) if len(present) else None),
            "lealtad": float(np.mean(leal)) if leal else None,
            "con_oficialismo": float(np.mean(conofi)) if conofi else None,
            "votos": dict(Counter(present)),
        })
    df = pd.DataFrame(filas)

    # bisagras: los más cercanos a la línea, de cada bloque; cruzados aparte
    if "linea" in out:
        df["bloque"] = df.id.map(lambda i: "oficialismo" if miembros[i]["grupo"] in OFICIALISMO
                                 else "oposicion" if miembros[i]["grupo"] in OPOSICION else "otro")
        df["lado"] = np.where(df.dist_linea.isna(), None,
                              np.where(df.dist_linea > 0, "oficialismo", "oposicion"))
        df["cruzado"] = df.lado.notna() & (df.lado != df.bloque) & (df.bloque != "otro")
        df["rank_bisagra"] = df.dist_linea.abs().rank(method="first")
    out["miembros"] = json.loads(df.to_json(orient="records"))

    # partidos
    part = []
    for grp, g in df.dropna(subset=["x"]).groupby(df.id.map(lambda i: miembros[i]["grupo"])):
        part.append({"grupo": grp, "n": len(g),
                     "x": float(g.x.median()), "y": float(g.y.median()),
                     "x_mean": float(g.x.mean()), "y_mean": float(g.y.mean()),
                     "sx": float(g.x.std(ddof=0)), "sy": float(g.y.std(ddof=0)),
                     "lealtad": float(g.lealtad.mean())})
    out["partidos"] = part
    out["votaciones_modelo"] = list(map(str, keep_v))
    return out


def run(camaras=("diputados", "senado")) -> dict:
    votos = pd.read_csv(DATA / "votos.csv", keep_default_na=False, dtype=str)
    votos = votos[votos.voto != "PRESIDENTE"].replace({"voto": {"ILEGIBLE": np.nan}})
    paginas = pd.read_csv(DATA / "paginas.csv", keep_default_na=False, dtype=str)
    roster = json.loads((DATA / "roster.json").read_text(encoding="utf-8"))
    res = {}
    for cam in camaras:
        res[cam] = estimate(cam, votos, roster, paginas)
        m = res[cam]
        if "lambda2" in m:
            print(f"  λ₂={m['lambda2']:.3f}  clasif 1D={m.get('clasif_1d', 0):.3f} "
                  f"2D={m.get('clasif_2d', 0):.3f}  robustez MDS={m['robustez_mds']:.2f} "
                  f"PCA={m['robustez_pca']:.2f}  línea: {m['linea']['errores']} "
                  f"miembros del lado contrario")
        (DATA / f"modelo_{cam}.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--camara", choices=["diputados", "senado"])
    a = ap.parse_args()
    run((a.camara,) if a.camara else ("diputados", "senado"))
