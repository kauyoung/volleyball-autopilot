"""
Camera timeline from clock times (2026-10-26, Kenny: "how do we fix this when the camera
unexpectedly stops?").

    C:\\Python314\\python.exe camera-time.py "<match folder>" [--dry-run]

Puts every point / time-out of the match folder's .json COPY onto the camera timeline using
real clock times, so camera stops in a set (SD card, battery, heat) or between sets need no
hand work:
  * clock time of each tap: the scorekeeper's "wms" (since 2026-10-26); older files: START +
    t + the stops the scorekeeper knew about (its "recordings" list)
  * where each camera clip sits in that clock: clip 1 starts at START - offset; later clips by
    the camera's file-name times (seamless chapter splits by duration)
  * a tap inside a camera stop lands 0.35 s after the restart (the score jumps under the wipe)
  * every real stop is written to "cameraGaps": inside a set -> CAMERA TECHNICAL DIFFICULTY
    wipe "camera-<clip>" with "M:SS OF SET n NOT RECORDED" (drawn by make-camera-wipe.py);
    between sets -> that set's SET n wipe moved onto the restart
  * "timeBase": "camera" makes apply-match.lua skip its own set alignment; offset becomes 0
    (the one used is kept as "offsetApplied")
The untouched copy is kept as "<name>.original.txt" (created once) and is always the source,
so a re-run gives the same answer. Prints "CAMERA TIME: ..." lines; "CAMERA TIME: no stops"
when the camera ran straight through (nothing changed then).
"""
import datetime, glob, json, os, re, subprocess, sys

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
PY = r"C:\Python314\python.exe"
FFPROBE = r"C:\ffmpeg\bin\ffprobe.exe"
SEAMLESS = 3.0          # s: a join this close to "start + duration" is a chapter split, not a stop
MIN_GAP = 3.0           # s: shorter stops are treated as seamless
NW = 0x08000000


def iso_s(x):
    return datetime.datetime.fromisoformat(x).timestamp()


def clip_list(folder):
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "DJI_*.MP4"))):
        mm = re.search(r"DJI_(\d{14})", os.path.basename(f))
        if not mm:
            continue
        c = datetime.datetime.strptime(mm.group(1), "%Y%m%d%H%M%S").timestamp()
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                           capture_output=True, text=True, timeout=30, creationflags=NW)
        out.append({"file": f, "cam": c, "dur": float(r.stdout.strip())})
    return out


def main(folder, dry=False):
    js = [p for p in glob.glob(os.path.join(folder, "*.json"))]
    if len(js) != 1:
        print(f"CAMERA TIME: skipped - {len(js)} .json files in the folder"); return 0
    jp = js[0]
    orig = jp[:-5] + ".original.txt"
    cur = json.load(open(jp, encoding="utf-8"))
    src = json.load(open(orig, encoding="utf-8")) if os.path.exists(orig) else cur
    # a fresh --offset (run-match writes "offset") wins; otherwise the one used last time
    offset = float(cur.get("offset") or cur.get("offsetApplied") or 0)
    ev, tos = src["events"], src.get("timeouts") or []
    clips = clip_list(folder)
    if not clips or not ev:
        print("CAMERA TIME: skipped - no clips or no points"); return 0

    # 1. clock time (s) of every tap
    start = (ev[0]["wms"] / 1000) if ev[0].get("wms") else iso_s(src["startedAt"])
    recs = [(iso_s(r["start"]), iso_s(r["end"]) if r.get("end") else None) for r in (src.get("recordings") or [])]
    pauses = []                                     # (scorekeeper t when the stop began, length s)
    run_t = 0.0
    for (a, b), (c, _) in zip(recs, recs[1:]):
        if b is None:
            break
        run_t += b - a
        pauses.append((run_t, c - b))
    def clock(x):
        if x.get("wms"):
            return x["wms"] / 1000
        t = float(x["t"])
        return start + t + sum(L for at, L in pauses if t >= at - 0.5)
    have_clock = sum(1 for x in ev if x.get("wms"))

    # 2. where each clip sits on that clock and on the timeline
    tl = 0.0
    for k, c in enumerate(clips):
        if k == 0:
            c["clock"] = start - offset
        else:
            p = clips[k - 1]
            seamless = abs(c["cam"] - (p["cam"] + p["dur"])) <= SEAMLESS
            c["clock"] = p["clock"] + p["dur"] if seamless else c["clock0"]
        if k == 0:
            for q in clips[1:]:
                q["clock0"] = c["clock"] + (q["cam"] - c["cam"])
        c["tl"] = tl
        tl += c["dur"]
    end_tl = tl
    joins = []                                       # real stops: (clip index, gap s)
    for k in range(1, len(clips)):
        p, c = clips[k - 1], clips[k]
        g = c["clock"] - (p["clock"] + p["dur"])
        if g >= MIN_GAP:
            joins.append((k, g))
    if not joins and not pauses:
        print("CAMERA TIME: no stops - camera ran straight through, nothing changed"); return 0

    def place(w):
        """clock -> timeline s; (timeline s, in a gap?)"""
        for k, c in enumerate(clips):
            if w < c["clock"]:
                return (c["tl"] + 0.35, True) if k else (0.0, True)
            if w < c["clock"] + c["dur"]:
                return (c["tl"] + (w - c["clock"]), False)
        return (end_tl - 0.05, True)

    new_ev, set_at = [], []
    for x in ev:
        w = clock(x)
        T, gap = place(w)
        y = dict(x); y["t"] = round(T, 3)
        new_ev.append(y); set_at.append((w, x["set"]))
    new_to, dropped = [], 0
    for x in tos:
        T, gap = place(clock(x))
        if gap:
            dropped += 1; continue
        y = dict(x); y["t"] = round(T, 3); new_to.append(y)

    gaps, lines = [], []
    for k, g in joins:
        c0 = clips[k - 1]["clock"] + clips[k - 1]["dur"]; c1 = clips[k]["clock"]
        before = [s for w, s in set_at if w <= c0]; after = [s for w, s in set_at if w >= c1]
        sb, sa = (before[-1] if before else 1), (after[0] if after else None)
        hm = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")
        mmss = f"{int(g) // 60}:{int(g) % 60:02d}"
        # points scored while the camera was off in the SAME set -> mid-set stop
        if sa is not None and sa == sb:
            note = f"{mmss} OF SET {sb} NOT RECORDED"
            gaps.append({"clip": k, "wipe": f"camera-{k}", "note": note, "gap_s": round(g, 1)})
            lines.append(f"CAMERA TIME: camera stopped in set {sb}: {mmss} not recorded ({hm(c0)}-{hm(c1)}) - CAMERA TECHNICAL DIFFICULTY wipe")
            if not dry:
                r = subprocess.run([PY, "-W", "ignore", os.path.join(W, "make-camera-wipe.py"), f"camera-{k}",
                                    "CAMERA TECHNICAL DIFFICULTY", note], cwd=W, capture_output=True, text=True,
                                   timeout=600, creationflags=NW)
                lines.append("CAMERA TIME: " + ((r.stdout.strip().splitlines() or ["wipe: no output"])[-1]))
        elif sa is not None:
            gaps.append({"clip": k, "set": sa, "gap_s": round(g, 1)})
            lines.append(f"CAMERA TIME: camera stopped between sets ({mmss}, {hm(c0)}-{hm(c1)}) - SET {sa} wipe on the restart")
    if dropped:
        lines.append(f"CAMERA TIME: {dropped} time-out(s) fell while the camera was off - left out")
    lines.append(f"CAMERA TIME: {len(new_ev)} points placed from {'clock times' if have_clock else 'START + scorekeeper times'}"
                 f" (offset {offset:g} s used)")
    if not dry:
        if not os.path.exists(orig):
            json.dump(cur, open(orig, "w", encoding="utf-8"), ensure_ascii=False)
        cur.update({"events": new_ev, "timeouts": new_to, "offset": 0, "offsetApplied": offset,
                    "timeBase": "camera", "cameraGaps": gaps})
        json.dump(cur, open(jp, "w", encoding="utf-8"), ensure_ascii=False)
    for l in lines:
        print(l)
    return 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sys.exit(main(a[0], "--dry-run" in sys.argv))
