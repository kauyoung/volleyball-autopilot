"""
Camera timeline from clock times (2026-10-26: "how do we fix this when the camera
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
SHORT_GAP = float(os.environ.get("CT_SHORT_GAP", 20.0))
CLOCK_OK = (-60.0, 120.0)  # 2026-11-03: record->START gaps the camera clock is trusted for (Nov 1: 2.9-4.7 s; the owner may
                           # wait 20 s+; negative = START tapped before recording). Outside = clock suspect
TC_JUMP = 2.5           # s: timecode vs file-name time of a later clip differing more than this = timecode jumped
TYPICAL = 4.0           # s: the owner's usual Mimo-record -> beep -> Safari START gap (last resort)
AUTO_MAX = 15.0         # s: the camera can't sensibly start more than this before START (else its clock is off)   # 2026-11-02: mid-set stops shorter than this = plain cut, no wipe
NW = 0x08000000


def tc_seconds(tc):
    """DJI 59.94 drop-frame timecode 'HH:MM:SS;FF' -> seconds (2026-11-02: frame-accurate clip starts)"""
    h, m, s, f = [int(x) for x in tc.replace(";", ":").split(":")]
    lab = ((h * 60 + m) * 60 + s) * 60 + f
    mins = h * 60 + m
    return (lab - 4 * (mins - mins // 10)) * 1001 / 60000


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
        q = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream_tags=timecode",
                            "-of", "csv=p=0", f], capture_output=True, text=True, timeout=30, creationflags=NW)
        try:
            tc = tc_seconds(q.stdout.strip())
        except Exception:
            tc = None
        out.append({"file": f, "cam": c, "dur": float(r.stdout.strip()), "tc": tc})
    # 2026-11-02: clips after the first are placed by the camera's frame-accurate timecode (the file-name
    # time is cut to whole seconds, which put restarts up to ~2 s off); file names only if a clip has no timecode
    TCJ.clear()
    if all(c["tc"] is not None for c in out):
        # 2026-11-03 fail-safe: if a restart reset the camera's timecode, the timecode and the file-name time of a
        # later clip disagree -> keep the file-name times (1 s steps) for every clip and say so
        bad = [os.path.basename(c["file"]) for c in out[1:]
               if abs((c["tc"] - out[0]["tc"]) - (c["cam"] - out[0]["cam"])) > TC_JUMP]
        if bad:
            TCJ.extend(bad)
        else:
            for c in out[1:]:
                c["cam"] = out[0]["cam"] + (c["tc"] - out[0]["tc"])
    return out


TCJ = []


CONFIRMED = []


def phone_check(fb, rec_cam, start):
    """2026-11-03 (#2): the scorekeeper page logs when it was hidden / shown (phone clock) in the 30 min before START.
    the owner presses record in Mimo while the page is hidden, then comes back and taps START. Returns None (no data),
    or {"ok": True} when the camera's record time falls in a hidden stretch, else {"ok": False, "offset": rough}."""
    if not fb:
        return None
    ev = sorted((x for x in fb if x.get("wms")), key=lambda x: x["wms"])
    spans, hid = [], None
    first_show = None
    for x in ev:
        w = x["wms"] / 1000
        if w > start + 180:
            break
        if x["v"] == "hide":
            hid = w
        elif x["v"] == "show":
            if x.get("load"):
                # 2026-11-09 (Nov 8): Safari reloaded the page - that is not the owner coming back
                # from Mimo, and what happened before it is unknown. Start over as if the page just opened.
                spans, hid, first_show = [], None, w
                continue
            if hid is not None:
                spans.append((hid, w)); hid = None
            elif first_show is None:
                first_show = w                      # page opened (or already open) - anything before is unknown
    if first_show is not None:
        spans.insert(0, (-1e18, first_show))
    if not spans:
        return None
    for a, b in spans:
        if a - 2.0 <= rec_cam <= b + 1.0:
            gap = start - rec_cam
            when = f"{gap:.0f} s before START" if gap >= 0 else f"{-gap:.0f} s after START"
            return {"ok": True, "text": f"camera clock confirmed by your phone - recording started while the scorekeeper was in "
                                        f"the background, {when}"}
    # 2026-11-04: only real "left the page and came back" stretches can estimate the record time; the page
    # simply being open (e.g. a stand-in pressing record on the camera itself) says nothing -> camera clock rules
    real = [sp for sp in spans if sp[0] > -1e17]
    before = [sp for sp in real if sp[1] <= start + 0.5 and start - sp[1] < 120]
    after = [sp for sp in real if sp[0] >= start - 0.5]
    if before:                                       # usual: record in Mimo, back to Safari ~2 s after the beep, START
        a, b = before[-1]
    elif after:                                      # START tapped first, then record
        a, b = after[0]
    else:
        return None                                  # nothing usable - fall back to the camera clock rules
    rough = start - max(a, b - 2.0)
    if not (-60.0 <= rough <= 120.0):
        return None
    if -2.0 <= start - rec_cam <= 10.0:
        # 2026-11-09: -2..0 s too - the file name is cut to whole seconds, and since Nov 8 the owner may tap START
        # first and press the camera's own record button a moment later (page never leaves the front).
        # 2026-11-04: the camera reports the usual 0-10 s record->START gap. The phone's last app switch can be
        # something else (a text message, record pressed on the camera itself) - trust the camera clock; the
        # video check still catches any small error (+-8 s is reliable)
        return None
    return {"ok": False, "offset": rough,
            "text": f"camera says recording started {start - rec_cam:.1f} s before START, but the scorekeeper page was in front "
                    f"then; last time away from it ended {start - b:.1f} s before START"}


def motion_offset(folder, hint=None):
    """2026-11-03: offset (s the camera started before START) measured by sync-check.py --measure.
    Returns (offset, detail) or (None, why-not)."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run([PY, "-W", "ignore", os.path.join(here, "sync-check.py"), "--measure", folder]
                           + (["--hint", f"{hint:.2f}"] if hint is not None else []), cwd=W,   # no hint = scan -60..+180 s
                           capture_output=True, text=True, timeout=3000, creationflags=NW,
                           env=dict(os.environ, SYNC_TC_JUMPED="1" if TCJ else "0"))
        line = [l for l in r.stdout.splitlines() if l.startswith("MEASURE ")][-1]
    except Exception as e:
        return None, f"failed ({type(e).__name__})"
    m = json.loads(line[8:]) or {}
    if hint is not None:
        loc = m.get("local")
        if not loc or loc["edge"] or loc["corr"] < 0.6:
            return None, "unclear" + (f" (match {loc['corr']:.2f})" if loc else "")
        return round(loc["need"], 2), f"video match {loc['corr']:.2f}"
    g = m.get("global")
    if not g:
        return None, "unclear (no usable points)"
    if not g["clear"]:
        return None, (f"unclear (best {g['need']:.1f} s match {g['corr']:.2f}, next best "
                      f"{g['rival_need']} s match {g['rival_corr']:.2f})")
    return round(g["need"], 2), f"whole-match pattern, match {g['corr']:.2f} vs next best {g['rival_corr']:.2f}"

def main(folder, dry=False):
    js = [p for p in glob.glob(os.path.join(folder, "*.json"))]
    if len(js) != 1:
        print(f"CAMERA TIME: skipped - {len(js)} .json files in the folder"); return 0
    jp = js[0]
    orig = jp[:-5] + ".original.txt"
    cur = json.load(open(jp, encoding="utf-8"))
    src = json.load(open(orig, encoding="utf-8")) if os.path.exists(orig) else cur
    ev, tos = src["events"], src.get("timeouts") or []
    clips = clip_list(folder)
    if not clips or not ev:
        print("CAMERA TIME: skipped - no clips or no points"); return 0

    # 1. clock time (s) of every tap
    start = (ev[0]["wms"] / 1000) if ev[0].get("wms") else iso_s(src["startedAt"])
    # 2026-11-02: the camera clock is synced to his phone by the DJI Mimo app, and he presses
    # record in Mimo first, waits for the beep, then taps START - so the camera really starts a few
    # seconds before START. Clip 1 is placed by the CAMERA clock (file-name time + 0.5 s, the name is
    # cut to whole seconds) instead of at START. Verified on Nov 1: Georgetown 4.7 s (the owner approved 5),
    # Niagara 2.9 s (motion check 3.0-3.4). A fresh --offset (run-match writes "offset") still wins.
    manual = cur.get("offset")
    if manual not in (None, 0, 0.0, "0"):
        offset, how = float(manual), "set by hand"
    else:
        auto = start - (clips[0]["cam"] + 0.5)
        phone = phone_check(src.get("focusBeforeStart"), clips[0]["cam"] + 0.5, start)
        if phone and phone["ok"]:
            # 2026-11-03 (#2): the camera started recording while the scorekeeper page was in the background (Mimo in
            # front) - the camera clock agrees with the phone, whatever the record->START wait was
            offset, how = round(auto, 2), "camera clock"
            CONFIRMED.append(phone["text"])
        elif phone:
            # camera clock disagrees with the phone -> rough offset from the phone, refined by the video within +-8 s
            print(f"CAMERA TIME: camera clock disagrees with your phone ({phone['text']}) - checking against the video", flush=True)
            rough = phone["offset"]
            mo, detail = motion_offset(folder, hint=rough)
            if mo is not None:
                offset, how = mo, f"phone + video check, camera clock was off by {auto - mo:+.1f} s ({detail})"
            else:
                offset, how = round(rough, 2), f"phone check, camera clock was off by {auto - rough:+.1f} s (video {detail}; +-2 s)"
        elif CLOCK_OK[0] <= auto <= CLOCK_OK[1]:
            offset, how = round(auto, 2), "camera clock"
        else:
            # 2026-11-03 ("really fix the timing"): camera clock looks off (Mimo didn't sync it,
            # phone time set by hand...) -> measure the offset from the motion pattern instead of guessing
            print(f"CAMERA TIME: camera clock looks off ({auto:+.1f} s) - measuring the timing from the video (motion check, ~1 min per 5 min of video)", flush=True)
            mo, detail = motion_offset(folder)
            if mo is not None:
                offset, how = mo, f"motion check, camera clock was off ({auto:+.1f} s): {detail}"
            else:
                # unclear: a clock value that is still possible (START tapped up to 60 s before recording) beats the
                # usual 4 s; otherwise the usual 4 s. FLAG either way; the upload is held by the sync check.
                fb = round(auto, 2) if -60.0 <= auto <= 120.0 else TYPICAL
                offset, how = fb, (f"camera clock looks off ({auto:+.1f} s) and motion check {detail} - placed at "
                                   + (f"the camera clock's {fb:g} s" if fb != TYPICAL else f"the usual {TYPICAL:g} s"))
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
    # 2026-11-02: no early return any more - even without stops the points are placed by the camera clock

    def place(w):
        """clock -> timeline s; (timeline s, in a gap?)"""
        for k, c in enumerate(clips):
            if w < c["clock"]:
                return (c["tl"] + 0.35, True) if k else (0.0, True)
            if w < c["clock"] + c["dur"]:
                return (c["tl"] + (w - c["clock"]), False)
        return (end_tl - 0.05, True)

    new_ev, set_at = [], []
    prev_sc = None
    for x in ev:
        w = clock(x)
        T, gap = place(w)
        y = dict(x); y["t"] = round(T, 3)
        new_ev.append(y)
        sc = (x.get("score1"), x.get("score2"))
        if sc != prev_sc and (x.get("score1") or x.get("score2")):      # real points only (2026-11-02)
            set_at.append((w, x["set"]))
        prev_sc = sc
    real_w = [w for w, _ in set_at]
    # time-outs: a tap inside a camera stop is no longer dropped (2026-11-02): it is put just
    # before the restart so the time-out cut covers the join
    new_to, to_clock = [], []
    for x in tos:
        w = clock(x)
        T, gap = place(w)
        y = dict(x)
        if gap:
            y["t"] = round(max(0.0, T - 0.35 - 6.0), 3); y["inCameraGap"] = True
        else:
            y["t"] = round(T, 3)
        if x.get("endW") or x.get("end_w"):                              # "Time-out over" tap (2026-11-02)
            Te, _ = place(float(x.get("endW") or x.get("end_w")) / 1000)
            y["end_t"] = round(Te, 3)
        new_to.append(y); to_clock.append((w, (float(x.get("endW") or x.get("end_w") or 0) / 1000) or None))
    dropped = 0

    gaps, lines = [], []
    hm = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")
    def in_timeout(c0, c1):
        """a time-out was running when the camera stopped: its tap is before the restart, no point was
        scored between the tap and the restart, and its "over" tap (if any) is after the stop began"""
        for tw, ew in to_clock:
            if tw <= c1 and not any(tw < w < c1 for w in real_w) and (ew is None or ew >= c0) and c0 - tw < 180:
                return True
        return False
    for k, g in joins:
        c0 = clips[k - 1]["clock"] + clips[k - 1]["dur"]; c1 = clips[k]["clock"]
        before = [s for w, s in set_at if w <= c0]; after = [s for w, s in set_at if w >= c1]
        sb, sa = (before[-1] if before else 1), (after[0] if after else None)
        mmss = f"{int(g) // 60}:{int(g) % 60:02d}"
        if sa is not None and sa == sb and in_timeout(c0, c1):
            lines.append(f"CAMERA TIME: camera stopped during a time-out in set {sb} ({mmss}, {hm(c0)}-{hm(c1)}) - "
                         "covered by the TIME-OUT cut, no camera wipe")
            continue
        if sa is not None and sa == sb and g < SHORT_GAP:
            lines.append(f"CAMERA TIME: short camera stop in set {sb} ({mmss}, {hm(c0)}-{hm(c1)}) - plain cut, no wipe")
            continue
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
                 f" (camera started {offset:g} s before START - {how})")
    if TCJ:
        lines.append(f"FLAG: the camera's timecode jumped after a restart ({', '.join(TCJ)}) - later clips placed by their "
                     f"file-name times instead (within ~1 s); the sync check will confirm")
    if offset < -2.0 and not CONFIRMED:             # 2026-11-09: START up to 2 s before record = normal
        lines.append(f"FLAG: the camera clock says START was tapped {-offset:g} s BEFORE recording started - right? "
                     f"(if not, the camera clock is off; points in those first seconds show at the very start)")
    if CONFIRMED:
        lines.append("CAMERA TIME: " + CONFIRMED[0])
    elif offset > 10 and how == "camera clock":
        lines.append(f"FLAG: the camera clock says you tapped START {offset:g} s after pressing record - right? "
                     f"(a longer wait than usual is fine; if not, the camera clock is off)")
    if how.startswith("camera clock looks off"):
        lines.append(f"FLAG: {how} - check the score timing on the review sheet")
    elif how.startswith("phone"):
        lines.append(f"FLAG: camera clock was off - score timing taken from your phone's check"
                     f"{' + the video' if how.startswith('phone + video') else ' (+-2 s, video unclear)'} instead ({offset:g} s); "
                     f"a quick look at the first points is enough")
    elif how.startswith("motion check"):
        lines.append(f"FLAG: camera clock was off - score timing taken from the motion check instead ({offset:g} s); "
                     f"a quick look at the first points is enough")
    if not dry:
        if not os.path.exists(orig):
            json.dump(cur, open(orig, "w", encoding="utf-8"), ensure_ascii=False)
        cur["tcJumped"] = bool(TCJ)
        cur["clockConfirmed"] = bool(CONFIRMED)    # 2026-11-03: phone agrees -> no "did you wait N s?" question
        cur["offsetHow"] = how                     # 2026-11-03: sync-check holds the upload unless camera clock / by hand
        cur.update({"events": new_ev, "timeouts": new_to, "offset": 0, "offsetApplied": offset,
                    "timeBase": "camera", "cameraGaps": gaps})
        json.dump(cur, open(jp, "w", encoding="utf-8"), ensure_ascii=False)
    for l in lines:
        print(l)
    return 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sys.exit(main(a[0], "--dry-run" in sys.argv))
