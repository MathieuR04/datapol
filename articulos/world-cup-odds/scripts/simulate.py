#!/usr/bin/env python3
"""Monte Carlo engine for the 2026 World Cup forecast.

Model philosophy (per project spec)
-----------------------------------
The ONLY market inputs are per-match odds:
  * Remaining GROUP matches  -> de-vigged 1X2 from the betting market
    (data/match_odds.json), expressed as an independent-Poisson goal model
    (lambda per team) so scorelines -> goal difference for tiebreakers.
  * Hypothetical KNOCKOUT matches -> no market exists, so probabilities come
    from a POWER RANKING (static Elo + in-tournament form).

Every other number -- reach R32 / R16 / QF / SF / Final / champion, group
finishing position, conditional opponent distributions, most-likely path,
and the projected bracket -- is DERIVED by simulating all matches independently.
No aggregate ("win cup" / "reach round") market is used as an input.

Run:   python3 scripts/simulate.py [n_sims]
Reads: data/tournament.json, data/match_odds.json, scripts/team_meta.json
       data/market.json (optional, sanity comparison only)
Writes: data/forecast.json
"""
import json, math, os, random, sys, datetime
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOUR = os.path.join(ROOT, "data", "tournament.json")
ODDS = os.path.join(ROOT, "data", "match_odds.json")
MKT  = os.path.join(ROOT, "data", "market.json")
OUT  = os.path.join(ROOT, "data", "forecast.json")

HOSTS = {"Mexico", "United States", "Canada"}
HOST_BOOST = 35.0          # Elo bump for hosts (knockout home advantage)
L0, KGOAL = 1.35, 0.50     # power-ranking Poisson goal model (knockouts / odds-less)
FORM_GAIN = 85.0           # max ~±85 Elo from in-tournament form
ROUNDS = ["R32", "R16", "QF", "SF", "F", "champion"]
RANK = {"GROUP": 0, "R32": 1, "R16": 2, "QF": 3, "SF": 4, "F": 5, "champion": 6}
NEXT = {"R32": "R16", "R16": "QF", "QF": "SF", "SF": "F", "F": "champion"}

def expected(diff):
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))

def poisson(lam, rng):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1

def fallback_lambdas(ra, rb):
    e = (ra - rb) / 400.0
    return L0 * math.exp(KGOAL * e), L0 * math.exp(-KGOAL * e)

# ---- power ranking: Elo + in-tournament form -------------------------------
def build_ratings(tour):
    elo = {t: tour["teams"][t]["elo"] for t in tour["teams"]}
    perf = defaultdict(list)
    for m in tour["played"]:
        h, a, hg, ag = m["home"], m["away"], m["hg"], m["ag"]
        if h not in elo or a not in elo:
            continue
        # form = result vs. Elo expectation. Beating a strong favourite (low eh)
        # earns a big boost; an expected win earns little; an upset loss is punished.
        eh = expected(elo[h] + (HOST_BOOST if h in HOSTS else 0)
                      - elo[a] - (HOST_BOOST if a in HOSTS else 0))
        rh = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        perf[h].append(rh - eh)
        perf[a].append((1 - rh) - (1 - eh))
    form = {t: (FORM_GAIN * sum(v) / len(v) if (v := perf.get(t)) else 0.0) for t in elo}
    rating = {t: elo[t] + form[t] for t in elo}
    return elo, form, rating

# ----------------------------------------------------------------------------
class Sim:
    def __init__(self, tour, rating, match_odds):
        self.rating = rating
        self.groups = tour["groups"]
        self.base = tour["standings"]
        self.bracket = tour["bracket"]
        self.round_of = tour["round_of"]
        self.team_group = {t: tour["teams"][t]["group"] for t in tour["teams"]}
        # actual knockout matchups already set (overrides slot resolution / 3rd-place matching)
        self.confirmed_ko = tour.get("confirmed_ko", {})

        # third-place bracket slots: (match_id, side) -> allowed group letters
        self.tslots = {}
        for mid, mt in self.bracket.items():
            for side in ("home", "away"):
                if mt[side].get("type") == "T":
                    self.tslots[(mid, side)] = set(mt[side]["groups"])

        # played scores per group (for head-to-head tiebreaker)
        self.played_by_group = {g: [] for g in self.groups}
        for m in tour["played"]:
            g = self.team_group.get(m["home"])
            if g and self.team_group.get(m["away"]) == g:
                self.played_by_group[g].append((m["home"], m["away"], m["hg"], m["ag"]))

        # remaining group fixtures per group, with per-team lambdas from market
        lam = {}
        for r in match_odds["matches"]:
            lam["|".join(sorted([r["home"], r["away"]]))] = {r["home"]: r["lam_home"],
                                                             r["away"]: r["lam_away"]}
        self.pair_lambda = lam          # market goal model for ANY priced match
        # actual results of knockout matches already played (incl. penalty winners)
        self.played_ko = {}
        for m in tour["played"]:
            h, a = m["home"], m["away"]
            if self.team_group.get(h) != self.team_group.get(a):
                w = m.get("winner")
                if not w:
                    w = h if m["hg"] > m["ag"] else a if m["ag"] > m["hg"] else None
                if w:
                    self.played_ko["|".join(sorted([h, a]))] = w
        self.rem_by_group = {g: [] for g in self.groups}
        for m in tour["remaining_group"]:
            g = self.team_group[m["home"]]
            key = "|".join(sorted([m["home"], m["away"]]))
            self.rem_by_group[g].append((m["home"], m["away"], lam.get(key)))

    def r(self, t):
        return self.rating[t] + (HOST_BOOST if t in HOSTS else 0)

    def knockout_winner(self, h, a, rng):
        # confirmed tie already priced by the market -> use its goal model;
        # otherwise power-ranking Poisson. Draw -> penalties (half the rating edge).
        mk = self.pair_lambda.get("|".join(sorted([h, a])))
        if mk:
            lh, la = mk[h], mk[a]
        else:
            lh, la = fallback_lambdas(self.r(h), self.r(a))
        hg, ag = poisson(lh, rng), poisson(la, rng)
        if hg > ag: return h
        if ag > hg: return a
        return h if rng.random() < expected((self.r(h) - self.r(a)) * 0.5) else a

    # ---- group ranking with 2026 tiebreakers ----
    def rank_group(self, teams, pts, gd, gf, results, rng):
        # 1) points; ties broken by head-to-head (pts, gd, gf among tied), then
        #    overall gd, overall gf, power rating, random.
        order = sorted(teams, key=lambda t: pts[t], reverse=True)
        out = []
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and pts[order[j]] == pts[order[i]]:
                j += 1
            cluster = order[i:j]
            if len(cluster) == 1:
                out.append(cluster[0])
            else:
                cs = set(cluster)
                hp = {t: 0 for t in cluster}; hgd = dict(hp); hgf = dict(hp)
                for a, b, ga, gb in results:
                    if a in cs and b in cs:
                        if ga > gb: hp[a] += 3
                        elif gb > ga: hp[b] += 3
                        else: hp[a] += 1; hp[b] += 1
                        hgd[a] += ga - gb; hgd[b] += gb - ga
                        hgf[a] += ga; hgf[b] += gb
                out.extend(sorted(cluster, reverse=True, key=lambda t: (
                    hp[t], hgd[t], hgf[t], gd[t], gf[t], self.rating[t], rng.random())))
            i = j
        return out

    def assign_thirds(self, third_groups):
        slots = sorted(self.tslots.items(),
                       key=lambda kv: len(kv[1] & set(third_groups)))
        groups = list(third_groups)
        res, used = {}, set()
        def bt(i):
            if i == len(slots):
                return True
            key, allowed = slots[i]
            for g in groups:
                if g not in used and g in allowed:
                    used.add(g); res[key] = g
                    if bt(i + 1):
                        return True
                    used.discard(g); res.pop(key, None)
            return False
        return res if bt(0) else None

    def run_once(self, rng, track=None):
        pts = {t: self.base[t]["pts"] for t in self.base}
        gd  = {t: self.base[t]["gd"] for t in self.base}
        gf  = {t: self.base[t]["gf"] for t in self.base}

        winners, runners, thirds, group_pos = {}, {}, {}, {}
        for g, teams in self.groups.items():
            results = list(self.played_by_group[g])
            for h, a, lam in self.rem_by_group[g]:
                if lam:                       # market-driven scoreline
                    hg, ag = poisson(lam[h], rng), poisson(lam[a], rng)
                else:                         # fallback: power ranking
                    lh, la = fallback_lambdas(self.r(h), self.r(a))
                    hg, ag = poisson(lh, rng), poisson(la, rng)
                results.append((h, a, hg, ag))
                gf[h] += hg; gf[a] += ag
                gd[h] += hg - ag; gd[a] += ag - hg
                if hg > ag: pts[h] += 3
                elif hg < ag: pts[a] += 3
                else: pts[h] += 1; pts[a] += 1
            order = self.rank_group(teams, pts, gd, gf, results, rng)
            winners[g], runners[g], thirds[g] = order[0], order[1], order[2]
            for i, t in enumerate(order):
                group_pos[t] = i + 1

        # best 8 third-placed teams
        tlist = sorted(self.groups, reverse=True, key=lambda g: (
            pts[thirds[g]], gd[thirds[g]], gf[thirds[g]], rng.random()))[:8]
        assign = self.assign_thirds(tlist) or {k: g for k, g in zip(self.tslots, tlist)}

        def resolve(slot, key):
            ty = slot.get("type")
            if ty == "W": return winners[slot["group"]]
            if ty == "R": return runners[slot["group"]]
            if ty == "T": return thirds[assign[key]]
            return None

        reached = defaultdict(lambda: "GROUP")
        for g in self.groups:
            reached[winners[g]] = "R32"; reached[runners[g]] = "R32"
        for g in tlist:
            reached[thirds[g]] = "R32"

        win_of = {}
        for mid in sorted(self.bracket, key=int):
            mt = self.bracket[mid]; rnd = self.round_of[mid]
            def part(side):
                s = mt[side]
                return win_of[str(s["match"])] if s.get("type") == "M" else resolve(s, (mid, side))
            ck = self.confirmed_ko.get(mid)
            if ck:                                  # actual matchup is known -> use it
                h, a = ck["home"], ck["away"]
            else:
                h, a = part("home"), part("away")
            if track:
                track(rnd, mid, h, a)
            pk = self.played_ko.get("|".join(sorted([h, a])))
            w = pk if pk else self.knockout_winner(h, a, rng)
            win_of[mid] = w
            nxt = NEXT[rnd]
            if RANK[nxt] > RANK[reached[w]]:
                reached[w] = nxt
        return reached, win_of, group_pos

# ----------------------------------------------------------------------------
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    rng = random.Random(20260623)

    tour = json.load(open(TOUR, encoding="utf-8"))
    match_odds = json.load(open(ODDS, encoding="utf-8"))
    market = json.load(open(MKT, encoding="utf-8")) if os.path.exists(MKT) else {}
    teams = list(tour["teams"])
    elo, form, rating = build_ratings(tour)

    sim = Sim(tour, rating, match_odds)
    counts = {r: Counter() for r in ROUNDS}
    group_finish = {t: Counter() for t in teams}
    opp = {t: {r: Counter() for r in ROUNDS[:-1]} for t in teams}
    reached_at = {t: {r: 0 for r in ROUNDS[:-1]} for t in teams}
    slot_occ = defaultdict(Counter)

    def track(rnd, mid, h, a):
        opp[h][rnd][a] += 1; opp[a][rnd][h] += 1
        reached_at[h][rnd] += 1; reached_at[a][rnd] += 1
        if rnd == "R32":
            slot_occ[(mid, "home")][h] += 1; slot_occ[(mid, "away")][a] += 1

    print(f"simulating n={n}...", file=sys.stderr)
    for _ in range(n):
        reached, win_of, gpos = sim.run_once(rng, track=track)
        for t, dr in reached.items():
            for r in ROUNDS:
                if RANK[dr] >= RANK[r]:
                    counts[r][t] += 1
        for t, pos in gpos.items():
            group_finish[t][pos] += 1

    teams_info = {}
    for t in teams:
        gp = group_finish[t]
        info = dict(
            group=tour["teams"][t]["group"], flag=tour["teams"][t]["flag"],
            code=tour["teams"][t]["code"], elo=round(elo[t]),
            form=round(form[t]), rating=round(rating[t]),
            survival={r: round(counts[r][t] / n, 4) for r in ROUNDS},
            group_finish={str(p): round(gp[p] / n, 4) for p in (1, 2, 3, 4)},
        )
        opp_dist, path = {}, {}
        for r in ROUNDS[:-1]:
            tot = reached_at[t][r]
            if tot:
                opp_dist[r] = [{"team": o, "p": round(c / tot, 4)}
                               for o, c in opp[t][r].most_common(6)]
                top = opp[t][r].most_common(1)[0]
                path[r] = {"team": top[0], "p": round(top[1] / tot, 4)}
        info["opponents"] = opp_dist
        info["path"] = path
        teams_info[t] = info

    proj = build_projected_bracket(tour, slot_occ, rating, n, sim.played_ko)
    ranking = sorted(teams, key=lambda t: rating[t], reverse=True)
    power = [dict(team=t, flag=tour["teams"][t]["flag"], code=tour["teams"][t]["code"],
                  rating=round(rating[t]), elo=round(elo[t]), form=round(form[t]))
             for t in ranking]

    out = dict(
        updated=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        n_sims=n, teams=teams_info, power=power, bracket=proj,
        meta=dict(hosts=sorted(HOSTS), source="ESPN/DraftKings per-match odds + Elo/form power ranking"),
    )
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\nchampion odds (derived)  vs  Polymarket (sanity only):", file=sys.stderr)
    for t in sorted(teams, key=lambda t: counts["champion"][t], reverse=True)[:10]:
        mk = market.get("champion", {}).get(t)
        print(f"  {t:16s} champ {counts['champion'][t]/n*100:4.1f}%  "
              f"R16 {counts['R16'][t]/n*100:5.1f}%  "
              f"(pm champ {mk*100:4.1f}%)" if mk else
              f"  {t:16s} champ {counts['champion'][t]/n*100:4.1f}%  R16 {counts['R16'][t]/n*100:5.1f}%",
              file=sys.stderr)
    print("wrote", OUT, file=sys.stderr)

def build_projected_bracket(tour, slot_occ, rating, n, played_ko=None):
    played_ko = played_ko or {}
    confirmed_ko = tour.get("confirmed_ko", {})
    bracket, round_of = tour["bracket"], tour["round_of"]
    # unique greedy assignment: a team can occupy only one R32 slot. Resolve the
    # most-confident slots first, each taking its top still-available team.
    slots = sorted((kv for kv in slot_occ.items() if kv[1]),
                   key=lambda kv: -kv[1].most_common(1)[0][1])
    occ, used = {}, set()
    for key, c in slots:
        pick = next((t for t, _ in c.most_common() if t not in used), None) \
               or c.most_common(1)[0][0]
        occ[key] = pick; used.add(pick)
    def confirmed(key):   # this slot is occupied by the same team in every sim
        c = slot_occ.get(key)
        return bool(c) and c.most_common(1)[0][1] == n
    win_of, out = {}, {}
    for mid in sorted(bracket, key=int):
        mt = bracket[mid]
        def part(side):
            s = mt[side]
            return win_of.get(str(s["match"])) if s.get("type") == "M" else occ.get((mid, side))
        ck = confirmed_ko.get(mid)
        if ck:
            h, a = ck["home"], ck["away"]
        else:
            h, a = part("home"), part("away")
        pk = played_ko.get("|".join(sorted([h, a]))) if (h and a) else None
        w = pk or (h if (h and a and rating.get(h, 0) >= rating.get(a, 0)) else (a or h))
        win_of[mid] = w
        out[mid] = dict(round=round_of[mid], home=h, away=a, winner=w, played=bool(pk),
                        hc=confirmed((mid, "home")), ac=confirmed((mid, "away")))
    return out

if __name__ == "__main__":
    main()
