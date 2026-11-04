"""
Volleyball Autopilot - automatic score-timing check per set (2026-11-02, Kenny: "there has to be a way for you to
check the time sync"; 2026-11-03: any record->START gap, wide search, cache).

    C:\\Python314\\python.exe sync-check.py "<match folder>"                   -> sync-check.txt (verdict)
    C:\\Python314\\python.exe sync-check.py --measure [--hint S] "<folder>"    -> one "MEASURE {json}" line

Averages how much the picture moves around every score tap of a set (players rally, then stop) and
compares that pattern with sync-template.json (Nov 1 Georgetown, timing approved by Kenny). The shift
that lines them up = the offset (s the camera started before START) that set needs.
- verdict mode searches +-8 s around the offset camera-time applied (so a 20 s or 90 s record->START gap
  is checked just as well as 4 s) and writes  SYNC CHECK: set n OK (+0.2 s ...)  or  FLAG: set n ...
- measure mode (camera clock looks off): searches around --hint, or with no hint scans -60..+180 s;
  reports per set the best match and whether a second, far-away match is almost as good (ambiguous).
Motion is cached per clip in W\\_sync-cache (keyed by size + modified time), so the background check after
a measurement doesn't decode the video again. Never changes anything.
"""
import glob, json, os, subprocess, sys, time
import numpy as np
W = r"C:\Users\YOURNAME\scoreboard-pipeline"
FF = r"C:\ffmpeg\bin\ffmpeg.exe"; FP = r"C:\ffmpeg\bin\ffprobe.exe"
FPS = 10.0; WIN = (-12.0, 8.0); NW = 0x08000000
LIMIT = 1.5      # s: |residual| above this -> FLAG
MARGIN = 0.04   # 2026-11-03: the pooled best match must beat the runner-up (> 3 s away) by this much to count as clear
MAXLAG = 40      # x 0.2 s = +-8 s per search window
CACHE = os.path.join(W, "_sync-cache")


def tc2s(tc):
    h, m, s, f = [int(x) for x in tc.replace(";", ":").split(":")]
    lab = ((h * 60 + m) * 60 + s) * 60 + f; mins = h * 60 + m
    return (lab - 4 * (mins - mins // 10)) * 1001 / 60000


def motion(c):
    st = os.stat(c)
    key = os.path.join(CACHE, f"{st.st_size}_{int(st.st_mtime)}.npy")
    if os.path.exists(key):
        return np.load(key)
    p = subprocess.Popen([FF, "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", c, "-vf",
                          f"scale_cuda=160:90:format=nv12,hwdownload,format=nv12,fps={FPS},format=gray", "-an", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=NW)
    prev, m = None, []
    while True:
        b = p.stdout.read(160 * 90 * 64)
        if not b:
            break
        a = np.frombuffer(b, np.uint8).reshape(-1, 90, 160).astype(np.int16)
        a2 = np.concatenate([prev[None], a]) if prev is not None else a
        m.extend(np.abs(np.diff(a2, axis=0)).mean(axis=(1, 2)).tolist()); prev = a[-1]
    p.wait()
    arr = np.array(m, np.float32)
    try:
        os.makedirs(CACHE, exist_ok=True)
        if p.returncode == 0 and len(arr):
            np.save(key, arr)
        for old in glob.glob(os.path.join(CACHE, "*.npy")):          # keep the cache small: 21 days
            if time.time() - os.path.getmtime(old) > 21 * 86400:
                os.remove(old)
    except Exception:
        pass
    return arr


def lag(x, ref, maxlag=MAXLAG):
    """best (corr, shift s) of x against ref within +-maxlag*0.2 s"""
    x = (x - x.mean()) / (x.std() + 1e-9); r = (ref - ref.mean()) / (ref.std() + 1e-9); best = (-2, 0)
    for L in range(-maxlag, maxlag + 1):
        a, b = (x[L:], r[:len(r) - L]) if L >= 0 else (x[:L], r[-L:])
        best = max(best, (float(np.corrcoef(a[10:-10], b[10:-10])[0, 1]), L * 0.2))
    return best


def main(folder, measure=False, hint=None):
    out = os.path.join(folder, "sync-check.txt")
    def done(text):
        if measure:
            print("MEASURE " + json.dumps({"sets": [], "skipped": text}))
        else:
            open(out, "w", encoding="utf-8").write(text + "\n")
    js = glob.glob(os.path.join(folder, "*.json"))
    orig = glob.glob(os.path.join(folder, "*.original.txt"))
    if len(js) != 1:
        return done("SYNC CHECK: skipped (no single .json)")
    cur = json.load(open(js[0], encoding="utf-8"))
    src = json.load(open(orig[0], encoding="utf-8")) if orig else cur
    off = float(cur.get("offsetApplied") or 0.0)
    tpl = json.load(open(os.path.join(W, "sync-template.json"), encoding="utf-8"))
    ref = np.array(tpl["curve"], np.float32); T0 = float(tpl["offset"])
    ev = src["events"]
    if not ev or not ev[0].get("wms"):
        return done("SYNC CHECK: skipped (no clock times in the scorekeeper file)")
    S = ev[0]["wms"] / 1000
    clips = sorted(glob.glob(os.path.join(folder, "DJI_*.MP4")))
    tcs = []
    for c in clips:
        r = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream_tags=timecode", "-of", "csv=p=0", c],
                           capture_output=True, text=True, creationflags=NW)
        tcs.append(tc2s(r.stdout.strip()))
    # 2026-11-03: same placement as camera-time for clips 2+ (timecode, or file-name times if the timecode jumped)
    rel = [t - tcs[0] for t in tcs]
    rel_tc_bad = cur.get("tcJumped") or os.environ.get("SYNC_TC_JUMPED") == "1"
    if rel_tc_bad:
        import datetime, re
        cams = [datetime.datetime.strptime(re.search(r"DJI_(\d{14})", os.path.basename(c)).group(1), "%Y%m%d%H%M%S").timestamp() for c in clips]
        rel = [c - cams[0] for c in cams]
    mot = [motion(c) for c in clips]

    sets_taps = {}
    prev = None
    for e in ev:
        sc = (e["score1"], e["score2"])
        if sc != prev and (e["score1"] or e["score2"]):
            sets_taps.setdefault(int(e["set"]), []).append(e["wms"] / 1000)
        prev = sc

    def curve(taps, base):
        """averaged motion around the taps with clip 1 placed at START - base"""
        segs = []
        for w in taps:
            for k, r0 in enumerate(rel):
                p = w - (S - base + r0)
                i0 = int(round((p + WIN[0]) * FPS)); i1 = i0 + int(round((WIN[1] - WIN[0]) * FPS))   # fixed length (2026-11-03)
                if i0 >= 0 and i1 < len(mot[k]):
                    seg = mot[k][i0:i1]; segs.append(seg / (np.median(seg) + 1e-6)); break
        if len(segs) < 8:
            return None, len(segs)
        cv = np.convolve(np.mean(segs, axis=0), np.ones(5) / 5, mode="same")[::2]
        return cv, len(segs)

    def best_near(taps, centre):
        """(corr, need, n, edge) searching +-8 s around offset 'centre'"""
        base = centre - T0
        cv, n = curve(taps, base)
        if cv is None:
            return None, n
        corr, L = lag(cv[:len(ref)], ref[:len(cv)])
        return (corr, base + T0 + L, n, abs(L) >= 7.8), n

    def global_scan(taps):
        """2026-11-03: all taps of the match pooled (false matches differ per set, the true one doesn't);
        scan offsets -60..+180 s. Returns best (corr, need), runner-up > 3 s away, and whether it is clear."""
        cands = []
        for cen in np.arange(-60.0, 181.0, 12.0):
            b, _ = best_near(taps, float(cen))
            if b is not None and not b[3]:
                cands.append((b[0], b[1]))
        if not cands:
            return None
        cands.sort(key=lambda c: -c[0])
        top = cands[0]
        rival = next((c for c in cands[1:] if abs(c[1] - top[1]) > 3.0), (0.0, None))
        clear = top[0] >= 0.6 and top[0] - rival[0] >= MARGIN
        return {"corr": round(top[0], 3), "need": round(top[1], 2), "rival_corr": round(rival[0], 3),
                "rival_need": rival[1] if rival[1] is None else round(rival[1], 2), "clear": bool(clear)}

    all_taps = sorted(w for v in sets_taps.values() for w in v)
    if measure and hint is not None:
        # 2026-11-03: refine a rough offset (from the phone's Safari hide/show times) within +-8 s - reliable,
        # because that is less than half a rally (~20 s), so no false match fits inside the window
        b, n = best_near(all_taps, float(hint))
        loc = None if b is None else {"corr": round(b[0], 3), "need": round(b[1], 2), "n": n, "edge": bool(b[3])}
        print("MEASURE " + json.dumps({"local": loc, "hint": hint, "sets": []}))
        return
    if measure:
        g = global_scan(all_taps)
        print("MEASURE " + json.dumps({"global": g, "sets": []}))
        return

    lines, meas = [], []
    for s in sorted(sets_taps):
        taps = sets_taps[s]
        if measure:
            centres = [hint] if hint is not None else list(np.arange(-60.0, 181.0, 12.0))
            cands = []
            for cen in centres:
                b, n = best_near(taps, cen)
                if b is not None and not b[3]:
                    cands.append(b)
            if not cands:
                meas.append({"set": s, "n": n, "corr": 0.0, "need": None, "edge": True}); continue
            cands.sort(key=lambda b: -b[0])
            top = cands[0]
            rival = next((b for b in cands[1:] if abs(b[1] - top[1]) > 3.0), None)
            meas.append({"set": s, "n": top[2], "corr": round(top[0], 3), "need": round(top[1], 2), "edge": False,
                         "rival_corr": round(rival[0], 3) if rival else None,
                         "rival_need": round(rival[1], 2) if rival else None})
            continue
        b, n = best_near(taps, off)
        if b is None:
            lines.append(f"SYNC CHECK: set {s} - too few points to check ({n})"); continue
        corr, need, n, edge = b
        resid = off - need                             # + = scores late, - = scores early
        if corr < 0.6 or edge:
            lines.append(f"SYNC CHECK: set {s} - pattern unclear (match {corr:.2f}), not judged")
        elif abs(resid) > LIMIT:
            # 2026-11-03: no confident "x s late" any more - rallies repeat every ~20 s, so a wrong clock can line up
            # with a false match; only "close to the applied timing" is reliable
            lines.append(f"FLAG: set {s} score timing doesn't line up with the video (nearest match {need:.1f} s, "
                         f"applied {off:.1f} s, match {corr:.2f}) - camera clock may be off; check the first points by eye")
        else:
            lines.append(f"SYNC CHECK: set {s} OK ({resid:+.1f} s, match {corr:.2f})")
    how = str(cur.get("offsetHow") or "camera clock")
    if how == "camera clock" and not (0.0 <= off <= 10.0) and not cur.get("clockConfirmed"):
        # 2026-11-03: an unusual record->START wait is fine if Kenny really waited - but a clock off by ~one rally
        # (~20 s) can fool the video check, so it is confirmed with Kenny (holds the tournament upload until then)
        when = f"{off:g} s after pressing record" if off > 0 else f"{-off:g} s BEFORE recording started"
        lines.append(f"FLAG: camera clock says START came {when} (usual 2-6 s after) - "
                     f"confirm with Kenny (else the camera clock is off)")
    if not (how == "camera clock" or how == "set by hand"):
        lines.append(f"FLAG: score timing was not taken from the camera clock ({how[:120]}) - check the first points by eye")
    bad = [l for l in lines if l.startswith("FLAG") or "unclear" in l]
    if False and bad:                                  # 2026-11-03: whole-match scan is not reliable (rally period ~20 s)
        g = global_scan(all_taps)
        if g and g["clear"] and abs(g["need"] - off) > LIMIT:
            lines.append(f"FLAG: whole-match check says the camera started {g['need']:.1f} s before START (applied {off:.1f} s; "
                         f"match {g['corr']:.2f}, next best {g['rival_corr']:.2f}) - re-run with --rebuild --offset {g['need']:.1f}")
        elif g and g["clear"]:
            lines.append(f"SYNC CHECK: whole match OK ({off - g['need']:+.1f} s, match {g['corr']:.2f}, next best {g['rival_corr']:.2f})")
        else:
            lines.append("FLAG: score timing could not be confirmed from the video"
                         + (f" (best {g['need']:.1f} s match {g['corr']:.2f} vs {g['rival_need']} s match {g['rival_corr']:.2f})" if g else "")
                         + " - check the first points by eye")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    args = sys.argv[1:]
    hint = None
    if "--hint" in args:
        i = args.index("--hint"); hint = float(args[i + 1]); del args[i:i + 2]
    a = [x for x in args if not x.startswith("--")]
    main(a[0], "--measure" in args, hint)
