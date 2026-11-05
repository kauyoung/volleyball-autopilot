"""
Volleyball Autopilot - match format correction (2026-11-02: Nov 1 Unity Apex was scored as best of 3
by mistake; the match was 2 sets total).

    C:\\Python314\\python.exe fix-format.py "<match folder>" --two-sets

Edits ONLY the match folder's copy of the scorekeeper file (and its .original.txt if camera-time made
one) - never the Google Drive original. --two-sets: format -> "2of2" (2 sets, all played), drops every
set-3+ tap and time-out (an accidental 3rd set is just the app waiting for points), adds an end marker
4 s after the last point, and recomputes the result (1-1 -> decided on total points, like the app).
Idempotent. Prints one "FORMAT: ..." line.
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


def main(folder):
    js = glob.glob(os.path.join(folder, "*.json"))
    if len(js) != 1:
        print(f"FORMAT: skipped - {len(js)} .json files in the folder"); return 1
    paths = [js[0]] + [p for p in glob.glob(os.path.join(folder, "*.original.txt"))]
    msg = None
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        d, dropped = fix(d)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        r = d["result"]
        msg = msg or (f"FORMAT: 2 sets total - {dropped} set-3 tap(s) dropped - result {r['sets1']}-{r['sets2']} in sets, "
                      f"{r['points1']}-{r['points2']} in points, winner team {r['winner']} by {r['decidedBy']}")
    print(msg)
    return 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--two-sets" not in sys.argv or not a:
        print(__doc__); sys.exit(2)
    sys.exit(main(a[0]))
