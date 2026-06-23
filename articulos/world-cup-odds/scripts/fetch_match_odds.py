#!/usr/bin/env python3
"""Fetch per-match betting odds (1X2 + totals) for every remaining group match
from ESPN's public scoreboard API (DraftKings prices). De-vig to fair
Home/Draw/Away probabilities and fit an independent-Poisson goal model
(lambda_home, lambda_away) that reproduces those probabilities -- this gives
consistent scorelines for goal-difference tiebreakers in the simulation.

These per-match odds are the ONLY market input to the model. Everything else
(advance probabilities, opponents, bracket, title odds) is derived by the
simulation in simulate.py.

Run:  python3 scripts/fetch_match_odds.py
Reads:  data/tournament.json, scripts/team_meta.json
Writes: data/match_odds.json
"""
import json, math, os, subprocess, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOUR = os.path.join(ROOT, "data", "tournament.json")
META = os.path.join(HERE, "team_meta.json")
OUT  = os.path.join(ROOT, "data", "match_odds.json")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={}"

# ESPN display name -> our canonical name (codes usually match, names sometimes don't)
ALIAS = {
    "Bosnia-Herzegovina": "Bosnia and Herzegovina", "Czechia": "Czech Republic",
    "Türkiye": "Turkey", "Turkiye": "Turkey", "Congo DR": "DR Congo",
    "Korea Republic": "South Korea", "IR Iran": "Iran", "Cabo Verde": "Cape Verde",
    "Côte d'Ivoire": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
}

def curl(url):
    return subprocess.run(["curl", "-s", "--max-time", "30", url],
                          capture_output=True, text=True).stdout

def am_to_prob(o):
    o = float(o)
    return 100.0 / (o + 100.0) if o > 0 else (-o) / (-o + 100.0)

# ---- Poisson goal model -----------------------------------------------------
_FACT = [math.factorial(k) for k in range(13)]
def pmf(lam, k):
    return math.exp(-lam) * lam ** k / _FACT[k]

def match_probs(lh, la, kmax=9):
    ph = pd = pa = 0.0
    ph_pmf = [pmf(lh, i) for i in range(kmax + 1)]
    pa_pmf = [pmf(la, j) for j in range(kmax + 1)]
    for i in range(kmax + 1):
        for j in range(kmax + 1):
            p = ph_pmf[i] * pa_pmf[j]
            if i > j: ph += p
            elif i == j: pd += p
            else: pa += p
    return ph, pd, pa

def fit_lambdas(tph, tpd, tpa, ou):
    """Grid + refine to find (lh, la) reproducing target 1X2, total near ou."""
    best = (9e9, ou / 2, ou / 2)
    lo, hi = max(0.8, ou - 1.0), ou + 1.3
    Ts = [lo + 0.05 * k for k in range(int((hi - lo) / 0.05) + 1)]
    for T in Ts:
        s = -2.5
        while s <= 2.5:
            lh, la = (T + s) / 2.0, (T - s) / 2.0
            if lh > 0.03 and la > 0.03:
                ph, pd, pa = match_probs(lh, la, 8)
                e = (ph - tph) ** 2 + (pd - tpd) ** 2 + (pa - tpa) ** 2
                if e < best[0]:
                    best = (e, lh, la)
            s += 0.05
    return round(best[1], 3), round(best[2], 3), best[0] ** 0.5

# ----------------------------------------------------------------------------
def main():
    tour = json.load(open(TOUR, encoding="utf-8"))
    meta = {k: v for k, v in json.load(open(META, encoding="utf-8")).items()
            if not k.startswith("_")}
    code2name = {v["code"]: k for k, v in meta.items()}
    ours = set(meta)

    def canon(name, abbr):
        if name in ours: return name
        if name in ALIAS: return ALIAS[name]
        if abbr in code2name: return code2name[abbr]
        return None

    # gather ESPN events across the matchday-3 window
    events = {}
    for off in range(0, 8):
        dt = (date(2026, 6, 23) + timedelta(days=off)).strftime("%Y%m%d")
        try:
            d = json.loads(curl(ESPN.format(dt)))
        except Exception:
            continue
        for e in d.get("events", []):
            events[e.get("id")] = e

    odds_by_pair = {}
    parsed, skipped = [], []
    for e in events.values():
        comp = e["competitions"][0]
        ods = comp.get("odds") or []
        cmp_by = {c["homeAway"]: c for c in comp["competitors"]}
        hn = canon(cmp_by["home"]["team"]["displayName"], cmp_by["home"]["team"].get("abbreviation"))
        an = canon(cmp_by["away"]["team"]["displayName"], cmp_by["away"]["team"].get("abbreviation"))
        if not hn or not an:
            continue
        o = next((x for x in ods if isinstance(x, dict) and x.get("moneyline")), None)
        if not o:
            skipped.append((hn, an, "no-odds")); continue
        ml = o.get("moneyline", {})
        def get_ml(side):
            x = ml.get(side, {})
            return (x.get("close") or x.get("open") or {}).get("odds")
        ho, ao, do = get_ml("home"), get_ml("away"), o.get("drawOdds", {}).get("moneyLine")
        ou = o.get("overUnder")
        if ho is None or ao is None or do is None or ou is None:
            skipped.append((hn, an, "incomplete")); continue
        rh, rd, ra = am_to_prob(ho), am_to_prob(do), am_to_prob(ao)
        s = rh + rd + ra
        ph, pd, pa = rh / s, rd / s, ra / s          # de-vig
        lh, la, ferr = fit_lambdas(ph, pd, pa, float(ou))
        rec = dict(date=e["date"][:10], home=hn, away=an,
                   p_home=round(ph, 4), p_draw=round(pd, 4), p_away=round(pa, 4),
                   total=float(ou), lam_home=lh, lam_away=la,
                   provider=o.get("provider", {}).get("name"), fit_err=round(ferr, 3))
        parsed.append(rec)
        odds_by_pair["|".join(sorted([hn, an]))] = rec

    # coverage vs our remaining fixtures
    have, missing = 0, []
    for m in tour["remaining_group"]:
        key = "|".join(sorted([m["home"], m["away"]]))
        if key in odds_by_pair: have += 1
        else: missing.append((m["home"], m["away"]))

    out = dict(source="espn-draftkings", matches=parsed)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"parsed {len(parsed)} matches with odds")
    print(f"coverage of remaining group fixtures: {have}/{len(tour['remaining_group'])}")
    if missing:
        print("MISSING odds (will use power-ranking fallback):")
        for h, a in missing: print("  ", h, "vs", a)
    worst = sorted(parsed, key=lambda r: -r["fit_err"])[:3]
    print("worst Poisson fit error:", [(r["home"], r["away"], r["fit_err"]) for r in worst])
    print("wrote", OUT)

if __name__ == "__main__":
    main()
