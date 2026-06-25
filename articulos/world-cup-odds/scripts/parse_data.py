#!/usr/bin/env python3
"""Parse the saved Wikipedia HTML of the 2026 FIFA World Cup into a structured
tournament.json: teams (group + flag + elo), current standings, remaining
group fixtures, and the full R32->Final bracket structure.

Run:  python3 scripts/parse_data.py
Reads:  data/source_wikipedia.html, scripts/team_meta.json
Writes: data/tournament.json
"""
import json, re, os, sys
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.path.join(ROOT, "data", "source_wikipedia.html")
META = os.path.join(HERE, "team_meta.json")
OUT  = os.path.join(ROOT, "data", "tournament.json")

def clean(s):
    return re.sub(r"\s+", " ", s).strip()

def strip_name(raw):
    """'Mexico (H, A)' -> 'Mexico'; drop trailing host/qualified annotations."""
    return clean(re.sub(r"\s*\([^)]*\)\s*$", "", raw))

def main():
    soup = BeautifulSoup(open(HTML, encoding="utf-8").read(), "html.parser")
    meta = {k: v for k, v in json.load(open(META, encoding="utf-8")).items()
            if not k.startswith("_")}

    # ---- 1. Standings per group ------------------------------------------
    groups = {}           # letter -> [team,...] in current standings order
    standings = {}        # team -> dict(pos,pld,w,d,l,gf,ga,gd,pts)
    for h in soup.find_all(["h2", "h3", "h4"]):
        m = re.match(r"^Group ([A-L])$", clean(h.get_text()))
        if not m:
            continue
        letter = m.group(1)
        sec = h.find_parent("section") or h
        table = None
        for tb in sec.find_all("table"):
            txt = clean(tb.get_text())[:140]
            if "Pld" in txt and "Pts" in txt:
                table = tb; break
        def num(s):  # strip footnote markers like '4[a]' and +/- signs
            s = re.sub(r"\[[^\]]*\]", "", s).replace("−", "-").replace("+", "").strip()
            return int(s)
        order = []
        for tr in table.find_all("tr"):
            c = [clean(x.get_text()) for x in tr.find_all(["td", "th"])]
            if len(c) < 10 or c[0] == "Pos":
                continue
            name = strip_name(c[1])
            order.append(name)
            standings[name] = dict(pos=num(c[0]), pld=num(c[2]), w=num(c[3]),
                                   d=num(c[4]), l=num(c[5]), gf=num(c[6]),
                                   ga=num(c[7]), gd=num(c[8]), pts=num(c[9]))
        groups[letter] = order

    all_teams = sorted(standings.keys())
    missing = [t for t in all_teams if t not in meta]
    if missing:
        print("ERROR: teams missing from team_meta.json:", missing, file=sys.stderr)
        sys.exit(1)

    # ---- 2. Matches (played / remaining group / confirmed knockout) ------
    team_group = {t: g for g, lst in groups.items() for t in lst}
    played, remaining_group, confirmed_ko = [], [], {}
    for b in soup.find_all("div", class_="footballbox"):
        th, ts, ta = b.find("th", "fhome"), b.find("th", "fscore"), b.find("th", "faway")
        if not (th and ts and ta):
            continue
        home, away, score = clean(th.get_text()), clean(ta.get_text()), clean(ts.get_text())
        home, away = strip_name(home), strip_name(away)
        if home not in standings or away not in standings:
            continue                                  # placeholder slot, e.g. "Winner Group A"
        sm = re.match(r"^(\d+)[–\-](\d+)$", score)
        mm = re.match(r"^Match (\d+)$", score)
        if sm:
            played.append(dict(home=home, away=away,
                               hg=int(sm.group(1)), ag=int(sm.group(2))))
        elif mm:
            if team_group[home] == team_group[away]:
                remaining_group.append(dict(home=home, away=away))
            else:                                     # cross-group => confirmed knockout tie
                confirmed_ko[mm.group(1)] = dict(home=home, away=away)

    # ---- 3. Bracket structure (official 2026 layout) ---------------------
    # Third-place slots list the 5 groups whose 3rd-placed team can land there.
    def W(g): return {"type": "W", "group": g}
    def R(g): return {"type": "R", "group": g}
    def T(groups_str): return {"type": "T", "groups": list(groups_str)}
    def M(n): return {"type": "M", "match": n}

    r32 = {
        73: (R("A"), R("B")),
        74: (W("E"), T("ABCDF")),
        75: (W("F"), R("C")),
        76: (W("C"), R("F")),
        77: (W("I"), T("CDFGH")),
        78: (R("E"), R("I")),
        79: (W("A"), T("CEFHI")),
        80: (W("L"), T("EHIJK")),
        81: (W("D"), T("BEFIJ")),
        82: (W("G"), T("AEHIJ")),
        83: (R("K"), R("L")),
        84: (W("H"), R("J")),
        85: (W("B"), T("EFGIJ")),
        86: (W("J"), R("H")),
        87: (W("K"), T("DEIJL")),
        88: (R("D"), R("G")),
    }
    later = {
        # Round of 16
        89: (M(74), M(77)), 90: (M(73), M(75)), 91: (M(76), M(78)), 92: (M(79), M(80)),
        93: (M(83), M(84)), 94: (M(81), M(82)), 95: (M(86), M(88)), 96: (M(85), M(87)),
        # Quarterfinals
        97: (M(89), M(90)), 98: (M(93), M(94)), 99: (M(91), M(92)), 100: (M(95), M(96)),
        # Semifinals
        101: (M(97), M(98)), 102: (M(99), M(100)),
        # Final
        104: (M(101), M(102)),
    }
    bracket = {str(k): dict(home=v[0], away=v[1]) for k, v in {**r32, **later}.items()}
    round_of = {}
    for n in range(73, 89): round_of[str(n)] = "R32"
    for n in range(89, 97): round_of[str(n)] = "R16"
    for n in range(97, 101): round_of[str(n)] = "QF"
    for n in (101, 102): round_of[str(n)] = "SF"
    round_of["104"] = "F"

    out = dict(
        updated=None,  # filled by simulate.py at run time
        teams={t: dict(group=g, **meta[t])
               for g, lst in groups.items() for t in lst},
        groups=groups,
        standings=standings,
        played=played,
        remaining_group=remaining_group,
        confirmed_ko=confirmed_ko,
        bracket=bracket,
        round_of=round_of,
    )
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"teams={len(out['teams'])} played={len(played)} "
          f"remaining_group={len(remaining_group)} confirmed_ko={len(confirmed_ko)} "
          f"bracket_matches={len(bracket)}")
    print("groups complete:", all(len(v) == 4 for v in groups.values()))
    print("wrote", OUT)

if __name__ == "__main__":
    main()
