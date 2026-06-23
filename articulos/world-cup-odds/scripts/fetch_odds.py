#!/usr/bin/env python3
"""Snapshot live Polymarket markets for the 2026 World Cup into data/market.json.

Pulls the round-by-round survival ladder (reach knockout / R16 / QF / SF / Final /
champion) plus group winner/second/last markets, normalises team names to our 48,
and stores de-vigged market-implied probabilities per team.

Uses curl (system Python's urllib has SSL issues on this machine).
Run:  python3 scripts/fetch_odds.py
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT  = os.path.join(ROOT, "data", "market.json")
META = os.path.join(HERE, "team_meta.json")
TAG  = "102350"  # 2026 FIFA World Cup

# Polymarket name -> our canonical name
ALIAS = {
    "USA": "United States", "Czechia": "Czech Republic",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Turkiye": "Turkey", "Türkiye": "Turkey", "Cabo Verde": "Cape Verde",
    "Korea Republic": "South Korea", "Republic of Korea": "South Korea",
    "Ivory Coast": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
    "Curacao": "Curaçao",
}

def curl(url):
    r = subprocess.run(["curl", "-s", "--max-time", "30", url],
                       capture_output=True, text=True)
    return r.stdout

def get_events():
    evs, seen = [], set()
    for off in range(0, 600, 100):
        url = (f"https://gamma-api.polymarket.com/events?tag_id={TAG}"
               f"&closed=false&limit=100&offset={off}")
        try:
            batch = json.loads(curl(url))
        except Exception:
            break
        if not isinstance(batch, list) or not batch:
            break
        for e in batch:
            if e.get("slug") not in seen:
                seen.add(e.get("slug")); evs.append(e)
        if len(batch) < 100:
            break
    return evs

def team_of(market, ours):
    raw = (market.get("groupItemTitle") or "").strip()
    if not raw:
        q = market.get("question", "")
        m = re.search(r"Will (.+?) (?:win|reach|advance|finish)", q)
        raw = m.group(1).strip() if m else ""
    name = ALIAS.get(raw, raw)
    return name if name in ours else None

def yes_price(market):
    op = market.get("outcomePrices")
    try:
        p = json.loads(op) if isinstance(op, str) else op
        outs = market.get("outcomes")
        outs = json.loads(outs) if isinstance(outs, str) else outs
        if outs and p and len(outs) == len(p):
            for o, v in zip(outs, p):
                if str(o).lower() == "yes":
                    return float(v)
        return float(p[0]) if p else None
    except Exception:
        return None

def extract(events, title_re, ours):
    """Return {team: yes_price} merging all events whose title matches."""
    out = {}
    rx = re.compile(title_re, re.I)
    for e in events:
        if not rx.search(e.get("title", "")):
            continue
        for m in e.get("markets", []):
            t = team_of(m, ours)
            p = yes_price(m)
            if t and p is not None:
                out[t] = p
    return out

def main():
    ours = {k for k in json.load(open(META, encoding="utf-8")) if not k.startswith("_")}
    events = get_events()
    print(f"fetched {len(events)} active WC events", file=sys.stderr)

    ladders = {
        "champion":  r"^World Cup Winner",
        "reach_R32": r"to advance to Knockout Stages",
        "reach_R16": r"To Reach Round of 16",
        "reach_QF":  r"To Reach Quarterfinals",
        "reach_SF":  r"To Reach Semifinals",
        "reach_F":   r"To Reach Final",
    }
    market = {k: extract(events, rx, ours) for k, rx in ladders.items()}

    # group position markets (winner / second / last) per group letter
    for pos, rx in (("winner", r"Group ([A-L]) Winner"),
                    ("second", r"Group ([A-L]) Second Place"),
                    ("last",   r"Group ([A-L]) Last Place")):
        market[f"group_{pos}"] = {}
        for e in events:
            mt = re.search(rx, e.get("title", ""))
            if not mt:
                continue
            g = mt.group(1)
            for m in e.get("markets", []):
                t = team_of(m, ours); p = yes_price(m)
                if t and p is not None:
                    market[f"group_{pos}"].setdefault(g, {})[t] = p

    out = {"source": "polymarket-gamma", "ladders": ladders, **market}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for k in ladders:
        print(f"{k:10s}: {len(market[k]):2d} teams")
    for pos in ("winner", "second", "last"):
        gk = market[f"group_{pos}"]
        print(f"group_{pos}: {len(gk)} groups, "
              f"{sum(len(v) for v in gk.values())} team-prices")
    print("wrote", OUT)

if __name__ == "__main__":
    main()
