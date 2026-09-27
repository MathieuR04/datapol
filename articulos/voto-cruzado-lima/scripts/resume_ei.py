import sys, numpy as np, pandas as pd
for ubi in sys.argv[1:]:
    ch = [pd.read_csv(f'ei_lambda_{ubi}_{s}.csv') for s in (1, 2)]
    x = pd.read_csv(f'ei_in_{ubi}.csv')
    for c in ch: c.columns = [k.removeprefix('lambda.') for k in c.columns]
    cols = ch[0].columns
    # R-hat (Gelman-Rubin) por celda con 2 cadenas
    n = len(ch[0]); A = np.stack([c.values for c in ch])        # (2, n, k)
    W = A.var(1, ddof=1).mean(0); B = n * A.mean(1).var(0, ddof=1)
    rhat = np.sqrt(((n-1)/n*W + B/n) / W)
    allv = pd.concat(ch)
    rows = sorted({c.split('.')[0] for c in cols}, key=lambda r: [c.split('.')[0] for c in cols].index(r))
    dcs = sorted({c.split('.')[1] for c in cols}, key=lambda r: [c.split('.')[1] for c in cols].index(r))
    M = pd.DataFrame({d: [100*allv[f'{r}.{d}'].mean() for r in rows] for d in dcs}, index=rows)
    L = pd.DataFrame({d: [f"{100*allv[f'{r}.{d}'].quantile(.05):.0f}–{100*allv[f'{r}.{d}'].quantile(.95):.0f}" for r in rows] for d in dcs}, index=rows)
    w = x[rows].sum() / x[rows].sum().sum()
    # recto = prov r -> dist r (mismo nombre, sin Otros)
    same = [(r, 'd_'+r[2:]) for r in rows if 'd_'+r[2:] in dcs and r != 'p_Otros']
    recto = sum(w[r] * allv[f'{r}.{d}'] for r, d in same)
    cz = 1 - recto
    print(f"\n=== {ubi}  mesas={len(x)}  rhat_max={rhat.max():.3f} (celdas>1.1: {(rhat>1.1).sum()}/{len(rhat)})")
    print(f"cruzado estimado {100*cz.mean():.1f}%  [90%: {100*cz.quantile(.05):.1f}–{100*cz.quantile(.95):.1f}]")
    print("P(voto distrital | voto provincial), %  —  filas: cédula de Lima (peso), columnas: distrital")
    M.index = [f"{r[2:]} ({100*w[r]:.0f}%)" for r in rows]; M.columns = [d[2:] for d in dcs]
    print(M.round(0).astype(int).to_string())
    L.index = M.index; L.columns = M.columns
    print("intervalos 90%:"); print(L.to_string())
