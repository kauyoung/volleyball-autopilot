"""
Home Team - match format correction (2026-11-02, the owner: Nov 1 Eastview Apex was scored as best of 3
by mistake; the match was 2 sets total).

    C:\\Python314\\python.exe fix-format.py "<match folder>" --two-sets

Edits ONLY the match folder's copy of the scorekeeper file (and its .original.txt if camera-time made
one) - never the Google Drive original. --two-sets: format -> "2of2" (2 sets, all played), drops every
set-3+ tap and time-out (an accidental 3rd set is just the app waiting for points), adds an end marker
4 s after the last point, and recomputes the result (1-1 -> decided on total points, like the app).
Idempotent. Prints one "FORMAT: ..." line.

2026-11-22 (FIXES-TODO #8, Nov 19 Polar scrimmage): --winner 1|2 = "count team N as the winners": the last set
(time ran out) no longer counts in the sets won - every tap of that set and the end marker carry the sets won
BEFORE it, so the FINAL screen, review sheet and YouTube text show e.g. 1-1 instead of 1-2 - and the result
names team N the winner (on points when the sets are level). Its taps stay, so the video still shows that set.
Can be combined with --two-sets (applied after it).
    C:\\Python314\\python.exe fix-format.py "<match folder>" --winner 1
"""
import datetime, glob, json, os, sys


def fix(d):
    fmt = dict(d.get("format") or {})
    pts = int(fmt.get("pts") or 25)
    d["format"] = {"code": "2of2" if pts == 25 else "2of2-15", "sets": 2, "mode": "all", "pts": pts, "decider": pts}
    ev = [e for e in d["events"] if int(e.get("set", 1)) <= 2]
    dropped = len(d["events"]) - len(ev)
    last = ev[-1]
    if dropped:                                           # end marker 4 s after the last point (the app's FINISH)
        m = dict(last)
        if m.get("wms"):
            m["wms"] = m["wms"] + 4000
            m["at"] = datetime.datetime.fromtimestamp(m["wms"] / 1000).astimezone().isoformat(timespec="seconds")
        m["t"] = round(float(m.get("t", 0)) + 4.0, 3)
        ev.append(m)
        d["endedAt"] = m.get("at", d.get("endedAt"))
    d["events"] = ev
    d["timeouts"] = [t for t in (d.get("timeouts") or []) if int(t.get("set", 1)) <= 2]
    d["forcedSets"] = [s for s in (d.get("forcedSets") or []) if int(s) <= 2]
    # set results from the last tap of each set
    fin = {}
    for e in ev:
        fin[int(e["set"])] = (e["score1"], e["score2"])
    s1 = sum(1 for a, b in fin.values() if a > b); s2 = sum(1 for a, b in fin.values() if b > a)
    p1 = sum(a for a, b in fin.values()); p2 = sum(b for a, b in fin.values())
    if s1 != s2:
        win, how = (1 if s1 > s2 else 2), "sets"
    elif p1 != p2:
        win, how = (1 if p1 > p2 else 2), "points"
    else:
        win, how = 0, "tie"
    d["result"] = {"sets1": s1, "sets2": s2, "points1": p1, "points2": p2, "winner": win, "decidedBy": how}
    return d, dropped


def force_winner(d, n, drop_last=True):
    """drop_last=False (after --two-sets): every remaining set counts, only the winner is forced"""
    ev = d["events"]
    last_set = max(int(e.get("set", 1)) for e in ev) if drop_last else None
    fin = {}
    for e in ev:
        fin[int(e["set"])] = (e["score1"], e["score2"])
    done = {k: v for k, v in fin.items() if k != last_set}
    s1 = sum(1 for a, b in done.values() if a > b); s2 = sum(1 for a, b in done.values() if b > a)
    for e in ev:
        if last_set is not None and int(e.get("set", 1)) == last_set:
            e["sets1"], e["sets2"] = s1, s2
    p1 = sum(a for a, b in fin.values()); p2 = sum(b for a, b in fin.values())
    how = "points" if s1 == s2 else "sets"
    d["result"] = {"sets1": s1, "sets2": s2, "points1": p1, "points2": p2, "winner": int(n), "decidedBy": how}
    warn = ""
    if how == "sets" and (s1 > s2) != (int(n) == 1):
        warn = " - WARNING: the counted sets say the other team won"
    elif how == "points" and (p1 > p2) != (int(n) == 1):
        warn = " - WARNING: the other team has more total points"
    return d, last_set, warn


def main(folder, two_sets=True, winner=None):
    js = glob.glob(os.path.join(folder, "*.json"))
    if len(js) != 1:
        print(f"FORMAT: skipped - {len(js)} .json files in the folder"); return 1
    paths = [js[0]] + [p for p in glob.glob(os.path.join(folder, "*.original.txt"))]
    msg = None
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        parts = []
        if two_sets:
            d, dropped = fix(d)
            parts.append(f"2 sets total - {dropped} set-3 tap(s) dropped")
        if winner:
            d, ls, warn = force_winner(d, winner, drop_last=not two_sets)
            parts.append(f"team {winner} counted as winners" + (f", set {ls} (time ran out) not counted" if ls else "") + warn)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        r = d["result"]
        msg = msg or (f"FORMAT: {' - '.join(parts)} - result {r['sets1']}-{r['sets2']} in sets, "
                      f"{r['points1']}-{r['points2']} in points, winner team {r['winner']} by {r['decidedBy']}")
    print(msg)
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    win = None
    if "--winner" in argv:
        i = argv.index("--winner")
        win = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
        if win not in ("1", "2"):
            print("FORMAT: skipped - --winner needs 1 or 2"); sys.exit(2)
    a = [x for x in argv if not x.startswith("--")]
    if ("--two-sets" not in argv and not win) or not a:
        print(__doc__); sys.exit(2)
    sys.exit(main(a[0], "--two-sets" in argv, win))
