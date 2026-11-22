"""
Scoreboard stills (2026-10-19, the owner: "go" on step 3 of the export-speed work).

Why: the live Fusion scoreboard caps the YouTube export at ~1x real time and makes it
slow down after 15-23 min (47 -> 30 fps). Pre-drawing the scoreboard as pictures and
laying them on the Match timeline exported last night's match at ~114 fps with no
slowdown, identical look (EXR half: max 0.12/255 vs the live scoreboard).

How (all inside the export phase of prepare-match.py, before the YouTube render):
  1. analyse   the scoreboard comp's keyframes -> holds (board doesn't change) and
               animated stretches (score pop, fades, serve icon ...)
  2. render    one EXR per hold + EXR frames for the animated stretches, from the
               "Scoreboard" timeline (Deliver jobs) into <drive>:\\Scoreboard stills\\<project>\\
  3. place     a new track "Scoreboard stills" directly above the live scoreboard (so the
               intro/summary/wipes still cover it), holds as stills, stretches as sequences
  4. check     coverage frame by frame, a few holds re-rendered and compared, one picture
               of the whole frame compared with the live scoreboard; then the live
               scoreboard clip is switched off (clip disabled, never deleted)
Anything unexpected -> everything is undone and the export runs with the live scoreboard
(the old way). After the export (export_status EXPORT OK) the track is removed and the
live scoreboard switched back on, so later edits see the timeline exactly as before.

Switch: W\\scoreboard-mode.txt = "live" turns it off for every match; PM_LIVE_SCOREBOARD
(run-match/run-tournament --live-scoreboard) for one run. Default: stills.

exec'd by prepare-match.py (sb_stills()); entry points: mode(), step(), consume(), restore().
"""
import glob, json, math, os, random, shutil, subprocess, time

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
PY = r"C:\Python314\python.exe"
FF = r"C:\ffmpeg\bin\ffmpeg.exe"
TRACK_NAME = "Scoreboard stills"
MP_FOLDER = "Scoreboard stills"
MIN_HOLD = 60                     # holds shorter than this are rendered frame by frame
FMT, CODEC, EXT = "exr", "RGBHalfZIP", ".exr"
MB_PER_FILE = 0.6                 # measured ~0.41 MB for a full board
STATIC_TOOLS = {"RectangleMask", "Merge", "Loader", "TextPlus", "BezierSpline", "Background",
                "Transform", "MediaOut", "MediaIn"}
MAX_BUILD_MIN = 75                # give up (-> live scoreboard) after this long
STALE_MIN = 15                    # an unfinished build untouched this long starts over
DETACHED = 0x00000008 | 0x08000000
# 2026-11-22 (the owner OK, replaces FIXES-TODO #5/#12): STRIP pictures - only a full-width strip around the board
# (measured on every build from sample frames, + STRIP_PAD) is rendered instead of the whole 3840x2160 frame:
# Scoreboard timeline output 3840 x h with "centerCrop" and the comp clip tilted so the strip is centred (Oct 27
# test: pixel-identical, 40 -> 25 s on the fixture). Placed pictures are tilted back down on the Match timeline.
# Anything outside the strip in a sample/check frame -> the build fails -> live scoreboard (as before).
# W\scoreboard-strip.txt = "off" -> full-frame pictures as before.
STRIP_PAD = 24
STRIP_HEIGHTS = (216, 240, 270, 360, 432, 540, 720, 1080)   # divisors of 2160 (see _strip_measure)
STRIP_ORIG = os.path.join(W, "sb-strip-orig.json")
STRIP_KEYS = ["useCustomSettings", "timelineOutputResMatchTimelineRes", "timelineOutputResolutionWidth",
              "timelineOutputResolutionHeight", "timelineOutputResMismatchBehavior"]


def strip_on():
    try:
        return open(os.path.join(W, "scoreboard-strip.txt"), encoding="utf-8").read().strip().lower() != "off"
    except Exception:
        return True


def _sb_comp_item(sbt):
    its = sbt.GetItemListInTrack("video", 1) or []
    return its[0] if its else None


def _strip_apply(p, sbt, stt):
    """Scoreboard timeline -> 3840 x h centre crop, comp clip tilted; originals saved first (undo survives a crash)"""
    it = _sb_comp_item(sbt)
    orig = {"project": p.GetName(), "settings": {k: sbt.GetSetting(k) for k in STRIP_KEYS},
            "tilt": float(it.GetProperty("Tilt") or 0), "active": True}
    json.dump(orig, open(STRIP_ORIG, "w", encoding="utf-8"))
    sp = stt["strip"]
    ok = [sbt.SetSetting("useCustomSettings", "1"), sbt.SetSetting("timelineOutputResMatchTimelineRes", "0"),
          sbt.SetSetting("timelineOutputResolutionWidth", "3840"), sbt.SetSetting("timelineOutputResolutionHeight", str(sp["h"])),
          sbt.SetSetting("timelineOutputResMismatchBehavior", "centerCrop"), it.SetProperty("Tilt", float(sp["tilt"]))]
    if not all(ok) or sbt.GetSetting("timelineOutputResolutionHeight") != str(sp["h"]):
        _strip_undo(p)
        raise RuntimeError(f"couldn't switch the Scoreboard timeline to strip output ({ok})")


def _strip_undo(p):
    """idempotent; called after the render, by restore() and on any failure"""
    try:
        orig = json.load(open(STRIP_ORIG, encoding="utf-8"))
    except Exception:
        return False
    if not orig.get("active") or orig.get("project") != p.GetName():
        return False
    sbt = _timeline(p, "Scoreboard")
    if not sbt:
        return False
    it = _sb_comp_item(sbt)
    for k in reversed(STRIP_KEYS):
        v = orig["settings"].get(k)
        if v is not None:
            sbt.SetSetting(k, v)
    if it:
        it.SetProperty("Tilt", float(orig.get("tilt") or 0))
    good = sbt.GetSetting("timelineOutputResolutionHeight") == orig["settings"].get("timelineOutputResolutionHeight")
    if not good:
        raise RuntimeError("couldn't put the Scoreboard timeline back to full frame (sb-strip-orig.json)")
    orig["active"] = False
    json.dump(orig, open(STRIP_ORIG, "w", encoding="utf-8"))
    return True


def _strip_measure(p, sbt, stt, runs):
    """render a few full frames (holds + animation middles), alpha box over them -> strip or None (= full frame)"""
    S = [r for r in runs if r[0] == "S"]; D = [r for r in runs if r[0] == "D"]
    rnd = random.Random(stt["started"])
    frames = sorted({S[0][1], S[-1][1]} | {r[1] for r in rnd.sample(S, min(2, len(S)))}
                    | {(r[1] + r[2]) // 2 for r in rnd.sample(D, min(3, len(D)))}
                    | {r[1] + 1 for r in rnd.sample(D, min(1, len(D)))})
    mdir = os.path.join(stt["run_dir"], "measure")
    os.makedirs(mdir, exist_ok=True)
    if p.GetCurrentTimeline().GetName() != "Scoreboard":
        p.SetCurrentTimeline(sbt)
    got = []
    for f in frames:
        g = _render_one(p, stt["T0s"] + f, mdir, f"m{f:07d}x", True, FMT, CODEC)
        if not g:
            return None, f"sample frame {f} didn't render"
        got.append(g)
    r = _compare(stt, ["bbox", got])
    if not isinstance(r, list) or r[0] is None:
        return None, f"no board found in the samples ({r})"
    need = (r[1] + 1 + STRIP_PAD) - (r[0] - STRIP_PAD)
    # strip height must divide 2160: Resolve scales a smaller picture's Tilt by its own height (Tilt T moves it
    # T * h / 2160 px), so the placement Tilt = -tilt * 2160 / h is then a whole number -> exact pixels
    h = next((x for x in STRIP_HEIGHTS if x >= need), None)
    if not h:
        return None, f"board area too tall for a strip ({need} px)"
    c = (r[0] + r[1] + 1) // 2
    y0 = min(max(0, c - h // 2), 2160 - h)
    return {"y0": y0, "h": h, "tilt": y0 + h // 2 - 1080, "place_tilt": -(y0 + h // 2 - 1080) * (2160 // h),
            "samples": len(got), "alpha_rows": r}, None




def mode():
    try:
        m = open(W + r"\scoreboard-mode.txt", encoding="utf-8").read().strip().lower()
        return "live" if m.startswith("live") else "stills"
    except Exception:
        return "stills"


# ---------------------------------------------------------------- helpers
def _timeline(p, name):
    for i in range(1, p.GetTimelineCount() + 1):
        t = p.GetTimelineByIndex(i)
        if t.GetName() == name:
            return t


def _sb_items(tl):
    out = []
    for k in range(1, tl.GetTrackCount("video") + 1):
        for it in tl.GetItemListInTrack("video", k) or []:
            mpi = it.GetMediaPoolItem()
            if it.GetName() == "Scoreboard" and mpi and mpi.GetClipProperty("Type") == "Timeline":
                out.append((k, it))
    return out


def _safe(s):
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in s).strip()


def _workroot(folder, project):
    return os.path.join(os.path.splitdrive(folder)[0] + "\\", "Scoreboard stills", _safe(project))


def _state_path(folder, project):
    return os.path.join(_workroot(folder, project), "state.json")


def _load(folder, project):
    try:
        return json.load(open(_state_path(folder, project), encoding="utf-8"))
    except Exception:
        return None


def _save(stt):
    stt["touched"] = time.time()
    os.makedirs(os.path.dirname(stt["state_path"]), exist_ok=True)
    tmp = stt["state_path"] + ".tmp"
    json.dump(stt, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, stt["state_path"])


def _log(stt, msg):
    try:
        with open(os.path.join(stt["run_dir"], "log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def _mp_folder(mp, create=True):
    root = mp.GetRootFolder()
    for f in root.GetSubFolderList() or []:
        if f.GetName() == MP_FOLDER:
            return f
    return mp.AddSubFolder(root, MP_FOLDER) if create else None


def _m(stt, f):
    """Match-timeline frame of comp frame f"""
    return stt["S2"] + (f - stt["L"])


# ---------------------------------------------------------------- restore
def restore(p, tl):
    """Remove the stills track + media, switch the live scoreboard clip back on. Idempotent.
    Raises if it can't (then nothing should be exported until it's sorted out)."""
    done = []
    if _strip_undo(p):
        done.append("Scoreboard timeline back to full frame")
    cur = p.GetCurrentTimeline()
    tracks = [k for k in range(1, tl.GetTrackCount("video") + 1) if tl.GetTrackName("video", k) == TRACK_NAME]
    if tracks:
        if not cur or cur.GetName() != tl.GetName():
            p.SetCurrentTimeline(tl)
        for k in sorted(tracks, reverse=True):
            if not tl.DeleteTrack("video", k):
                raise RuntimeError(f"couldn't remove the '{TRACK_NAME}' track (V{k})")
        done.append(f"stills track removed (V{','.join(map(str, tracks))})")
    for k, it in _sb_items(tl):
        if not it.GetClipEnabled():
            it.SetClipEnabled(True)
            if not it.GetClipEnabled():
                raise RuntimeError("couldn't switch the live scoreboard clip back on")
            done.append(f"live scoreboard (V{k}) switched back on")
    mp = p.GetMediaPool()
    f = _mp_folder(mp, create=False)
    if f:
        clips = f.GetClipList() or []
        if clips:
            mp.DeleteClips(clips)
        mp.DeleteFolders([f])
        done.append("stills removed from the media pool")
    if cur and p.GetCurrentTimeline().GetName() != cur.GetName():
        p.SetCurrentTimeline(cur)
    return done


# ---------------------------------------------------------------- 1. analyse
def _text_changes(tool, iid, k0, k1, cuts, calls):
    g = lambda f: tool.GetInput(iid, f)
    stack = [(k0, g(k0), k1, g(k1))]
    calls[0] += 2
    while stack:
        a, va, b, vb = stack.pop()
        if va == vb:
            continue
        if b - a <= 1:
            cuts.add(b)
            continue
        m = (a + b) // 2
        vm = g(m); calls[0] += 1
        stack += [(a, va, m, vm), (m, vm, b, vb)]


def analyse(comp, A, B):
    """Comp frames [A, B) -> runs [[kind, a, b], ...]; S = unchanging hold, D = render every frame."""
    tools = comp.GetToolList(False)
    kinds = {t.GetAttrs()["TOOLS_RegID"] for t in tools.values()}
    bad = sorted(kinds - STATIC_TOOLS)
    if bad:
        raise RuntimeError("the scoreboard uses tool types the stills check doesn't know: " + ", ".join(bad))
    for t in tools.values():
        if t.GetAttrs()["TOOLS_RegID"] == "Loader":
            ln = t.GetAttrs().get("TOOLIT_Clip_Length")
            if isinstance(ln, dict) and any((v or 0) > 1 for v in ln.values()):
                raise RuntimeError(f"loader {t.Name} is a moving clip, not a picture")
        for inp in t.GetInputList().values():
            try:
                e = inp.GetExpression()
            except Exception:
                e = None
            if e:
                raise RuntimeError(f"expression on {t.Name}.{inp.Name}")
    cuts, dyn, seen, calls = set(), [], set(), [0]
    for t in tools.values():
        if t.GetAttrs()["TOOLS_RegID"] == "BezierSpline":
            continue
        for inp in t.GetInputList().values():
            o = inp.GetConnectedOutput()
            if not o:
                continue
            sp = o.GetTool()
            if sp.GetAttrs()["TOOLS_RegID"] != "BezierSpline" or sp.Name in seen:
                continue
            seen.add(sp.Name)
            kf = sp.GetKeyFrames() or {}
            text = "Value" in kf
            keys = sorted((float(f), v) for f, v in kf.items() if not isinstance(f, str))
            iid = inp.GetAttrs()["INPS_ID"]
            for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
                if f1 <= A or f0 >= B:
                    continue
                if text:
                    _text_changes(t, iid, int(math.floor(f0)), int(math.ceil(f1)), cuts, calls)
                    continue
                flat = (v0.get(1) == v1.get(1)
                        and abs((v0.get("RH") or {}).get(2, 0.0)) < 1e-12
                        and abs((v1.get("LH") or {}).get(2, 0.0)) < 1e-12)
                if flat:
                    continue
                s, e = int(math.floor(f0)) + 1, int(math.ceil(f1))
                if e > s:
                    dyn.append((s, e)); cuts.add(s)
                cuts.add(e)
    bounds = [A] + sorted(c for c in cuts if A < c < B) + [B]
    mask = bytearray(B - A)
    for s, e in dyn:
        s, e = max(s, A), min(e, B)
        if e > s:
            mask[s - A:e - A] = b"\x01" * (e - s)
    runs = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        k = "D" if mask[a - A] else "S"
        if k == "S" and b - a < MIN_HOLD:
            k = "D"
        if runs and k == "D" and runs[-1][0] == "D" and runs[-1][2] == a:
            runs[-1][2] = b
        else:
            runs.append([k, a, b])
    return runs, {"splines": len(seen), "text_calls": calls[0], "cuts": len(cuts)}


# ---------------------------------------------------------------- compare helper
CMP = r'''
import subprocess, sys, json, numpy as np
FF = r"%s"
def load(f, fmt):
    raw = subprocess.run([FF, "-v", "error", "-i", f, "-f", "rawvideo", "-pix_fmt", fmt, "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint16).astype(np.int32)
out = []
args = json.loads(sys.argv[1])
if args and args[0] == "bbox":                 # 2026-11-22: alpha bounding box over full frames -> [ymin, ymax] or None
    lo, hi = None, None
    for f in args[1]:
        x = load(f, "rgba64le")
        if x.size != 3840 * 2160 * 4:
            print(json.dumps("bad size")); sys.exit()
        al = x.reshape(2160, 3840, 4)[:, :, 3]
        rows = np.nonzero(al.max(axis=1) > 0)[0]
        if rows.size:
            lo = int(rows[0]) if lo is None else min(lo, int(rows[0]))
            hi = int(rows[-1]) if hi is None else max(hi, int(rows[-1]))
    print(json.dumps([lo, hi])); sys.exit()
for e in args:
    a, b, fmt = e[:3]
    x, y = load(a, fmt), load(b, fmt)
    outside = 0
    if len(e) == 5 and x.size == 3840 * 2160 * 4:   # 2026-11-22 strip pictures: a = full frame, b = strip y0..y0+h
        y0, h = e[3], e[4]
        f_ = x.reshape(2160, 3840, 4)
        al = f_[:, :, 3].copy(); al[y0:y0 + h] = 0
        outside = int(al.max())
        x = f_[y0:y0 + h].reshape(-1)
    if x.size == 0 or x.size != y.size:
        out.append(None); continue
    d = np.abs(x - y)
    out.append([round(float(d.max()) / 257, 3), int((d > 257).sum())] + ([outside] if len(e) == 5 else []))
print(json.dumps(out))
''' % FF


def _compare(stt, pairs):
    """pairs [(file_a, file_b, pix_fmt)] -> [[max diff in 8-bit levels, count > 1 level] | None]"""
    f = os.path.join(stt["run_dir"], "cmp.py")
    if not os.path.exists(f):
        open(f, "w", encoding="utf-8").write(CMP)
    r = subprocess.run([PY, f, json.dumps(pairs)], capture_output=True, text=True, timeout=50,
                       creationflags=0x08000000)
    return json.loads(r.stdout or "null")


def _render_one(p, frame, tdir, name, alpha, fmt, codec, wait=25):
    p.DeleteAllRenderJobs()
    p.SetCurrentRenderFormatAndCodec(fmt, codec)
    p.SetRenderSettings({"SelectAllFrames": False, "MarkIn": frame, "MarkOut": frame, "TargetDir": tdir,
                         "CustomName": name, "ExportVideo": True, "ExportAudio": False, "ExportAlpha": alpha})
    j = p.AddRenderJob()
    p.StartRendering([j], False)
    t0 = time.time()
    while p.IsRenderingInProgress() and time.time() - t0 < wait:
        time.sleep(0.2)
    p.DeleteAllRenderJobs()
    got = glob.glob(os.path.join(tdir, name + "*"))
    return got[0] if got else None


# ---------------------------------------------------------------- the build, step by step
def _fresh(p, tl, folder):
    project = p.GetName()
    root = _workroot(folder, project)
    done = restore(p, tl)
    sbt = _timeline(p, "Scoreboard")
    if not sbt:
        raise RuntimeError("no Scoreboard timeline")
    items = _sb_items(tl)
    if len(items) != 1:
        raise RuntimeError(f"expected one live scoreboard clip on the Match timeline, found {len(items)}")
    k2, it2 = items[0]
    pr = it2.GetProperty()
    plain = {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "RotationAngle": 0.0, "CropLeft": 0.0,
             "CropRight": 0.0, "CropTop": 0.0, "CropBottom": 0.0, "Opacity": 100.0, "CompositeMode": 0}
    odd = [k for k, v in plain.items() if k in pr and abs(float(pr[k]) - v) > 1e-6]
    if odd or pr.get("FlipX") or pr.get("FlipY"):
        raise RuntimeError("the live scoreboard clip has been moved/resized (" + ", ".join(odd) + ")")
    comps = sbt.GetItemListInTrack("video", 1) or []
    comp = comps[0].GetFusionCompByIndex(1) if comps else None
    if not comp:
        raise RuntimeError("no scoreboard comp on the Scoreboard timeline")
    T0s = sbt.GetStartFrame()
    N = sbt.GetEndFrame() - T0s
    L = it2.GetLeftOffset()
    A, B = max(0, L), min(N, L + it2.GetDuration())
    t0 = time.time()
    runs, info = analyse(comp, A, B)
    files = sum(1 if k == "S" else b - a for k, a, b in runs)
    need = files * MB_PER_FILE / 1000 + 1
    free = shutil.disk_usage(os.path.splitdrive(folder)[0] + "\\").free / 1e9
    if free < need:
        raise RuntimeError(f"not enough space for the stills ({free:.0f} GB free, need ~{need:.0f} GB)")
    if not any(k == "D" for k, a, b in runs):
        raise RuntimeError("no animated stretches found — that doesn't look right")
    # tidy: older builds of this project, and other projects' builds older than a day
    os.makedirs(root, exist_ok=True)
    for d in glob.glob(os.path.join(root, "run *")):
        shutil.rmtree(d, ignore_errors=True)
    for d in glob.glob(os.path.join(os.path.dirname(root), "*")):
        if os.path.isdir(d) and os.path.normcase(d) != os.path.normcase(root) and time.time() - os.path.getmtime(d) > 86400:
            shutil.rmtree(d, ignore_errors=True)
    run_dir = os.path.join(root, "run " + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir)
    stt = {"state_path": os.path.join(root, "state.json"), "project": project, "tl": tl.GetName(),
           "run_dir": run_dir, "stage": "queue", "started": time.time(), "runs": runs, "A": A, "B": B,
           "T0s": T0s, "S2": it2.GetStart(), "L": L, "k2": k2, "queued": 0, "jobs": [], "files": files,
           "info": info, "analyse_s": round(time.time() - t0, 1), "restored": done, "consumed": False}
    _log(stt, f"analysed in {stt['analyse_s']} s: {len(runs)} runs, "
              f"{sum(1 for r in runs if r[0] == 'S')} holds, {sum(r[2] - r[1] for r in runs if r[0] == 'D')} frames; {info}")
    json.dump(runs, open(os.path.join(run_dir, "plan.json"), "w"))
    stt["strip"] = None
    if strip_on():
        t1 = time.time()
        stt["strip"], why = _strip_measure(p, sbt, stt, runs)
        _log(stt, (f"strip pictures: rows {stt['strip']['y0']}-{stt['strip']['y0'] + stt['strip']['h']} "
                   f"({stt['strip']['h']} px, tilt {stt['strip']['tilt']}), measured in {time.time() - t1:.0f} s")
             if stt["strip"] else f"strip pictures off for this build: {why} - full frames")
    _save(stt)
    return stt


def _name(k, a):
    return f"{k.lower()}{a:07d}x"     # ends in a letter: Resolve then adds the frame number directly


def _queue(p, stt, end):
    sbt = _timeline(p, "Scoreboard")
    if p.GetCurrentTimeline().GetName() != "Scoreboard":
        p.SetCurrentTimeline(sbt)
    if stt["queued"] == 0:
        p.DeleteAllRenderJobs()
        if stt.get("strip"):
            _strip_apply(p, sbt, stt)
    if not p.SetCurrentRenderFormatAndCodec(FMT, CODEC):
        raise RuntimeError("couldn't set the EXR render format")
    runs, T0 = stt["runs"], stt["T0s"]
    while stt["queued"] < len(runs) and time.time() < end:
        k, a, b = runs[stt["queued"]]
        p.SetRenderSettings({"SelectAllFrames": False, "MarkIn": T0 + a, "MarkOut": T0 + (a if k == "S" else b - 1),
                             "TargetDir": stt["run_dir"], "CustomName": _name(k, a), "ExportVideo": True,
                             "ExportAudio": False, "ExportAlpha": True})
        j = p.AddRenderJob()
        if not j:
            raise RuntimeError("couldn't add a render job")
        stt["jobs"].append(j); stt["queued"] += 1
    if stt["queued"] == len(runs):
        if not p.StartRendering(stt["jobs"], False):
            raise RuntimeError("Resolve didn't start rendering the stills")
        stt["stage"] = "render"; stt["render_started"] = time.time()
        _log(stt, f"{len(runs)} render jobs started")
    _save(stt)


def _expected(stt):
    T0, out = stt["T0s"], {}
    for k, a, b in stt["runs"]:
        n = _name(k, a)
        out[(k, a)] = [f"{n}{T0 + a:08d}{EXT}"] if k == "S" else [f"{n}{T0 + f:08d}{EXT}" for f in range(a, b)]
    return out


def _render_wait(p, stt):
    have = set(os.listdir(stt["run_dir"]))
    exp = _expected(stt)
    total = sum(len(v) for v in exp.values())
    got = sum(1 for v in exp.values() for f in v if f in have)
    if p.IsRenderingInProgress():
        el = time.time() - stt["render_started"]
        eta = el / got * (total - got) if got > 20 else None
        return f"drawing the scoreboard pictures {100 * got // total}%" + (f" (~{eta / 60:.0f} min left)" if eta else "")
    missing = [f for v in exp.values() for f in v if f not in have]
    if missing:
        raise RuntimeError(f"{len(missing)} scoreboard pictures weren't rendered (e.g. {missing[0]}) — render stopped?")
    p.DeleteAllRenderJobs()
    if stt.get("strip"):
        _strip_undo(p)                         # live scoreboard back to full frame before anything else
    stt["render_s"] = round(time.time() - stt["render_started"])
    stt["stage"] = "import"
    _log(stt, f"rendered {total} files in {stt['render_s']} s")
    _save(stt)
    return None


def _import(p, tl, stt, end):
    mp = p.GetMediaPool()
    fold = _mp_folder(mp)
    mp.SetCurrentFolder(fold)
    T0 = stt["T0s"]
    have = {c.GetClipProperty("File Name") for c in fold.GetClipList() or []}
    holds, seqs = [], []
    for k, a, b in stt["runs"]:
        n = _name(k, a)
        if k == "S":
            hn = f"hold-{a:07d}-x{EXT}"
            if hn not in have:
                dst = os.path.join(stt["run_dir"], hn)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(stt["run_dir"], f"{n}{T0 + a:08d}{EXT}"), dst)
                holds.append(dst)
        elif not any(h.startswith(n) for h in have):
            seqs.append({"FilePath": os.path.join(stt["run_dir"], n + "%08d" + EXT),
                         "StartIndex": T0 + a, "EndIndex": T0 + b - 1})
    for i in range(0, len(holds), 100):
        if time.time() > end:
            return "importing the pictures"
        got = mp.ImportMedia(holds[i:i + 100]) or []
        if len(got) != len(holds[i:i + 100]):
            raise RuntimeError(f"imported {len(got)} of {len(holds[i:i + 100])} hold pictures")
    for i in range(0, len(seqs), 50):
        if time.time() > end:
            return "importing the pictures"
        got = mp.ImportMedia(seqs[i:i + 50]) or []
        if len(got) != len(seqs[i:i + 50]):
            raise RuntimeError(f"imported {len(got)} of {len(seqs[i:i + 50])} animated stretches")
    # the new track, directly above the live scoreboard (below intro/summary/wipes)
    if p.GetCurrentTimeline().GetName() != tl.GetName():
        p.SetCurrentTimeline(tl)
    k2 = stt["k2"]
    before = [len(tl.GetItemListInTrack("video", k) or []) for k in range(1, tl.GetTrackCount("video") + 1)]
    if not tl.AddTrack("video", {"index": k2 + 1}):
        raise RuntimeError("couldn't add the stills track")
    after = [len(tl.GetItemListInTrack("video", k) or []) for k in range(1, tl.GetTrackCount("video") + 1)]
    if after != before[:k2] + [0] + before[k2:]:
        tl.DeleteTrack("video", len(after)) if after[-1] == 0 else None
        raise RuntimeError(f"the stills track didn't go in above the scoreboard ({before} -> {after})")
    tl.SetTrackName("video", k2 + 1, TRACK_NAME)
    stt["K"] = k2 + 1
    stt["stage"] = "place_d"; stt["i"] = 0
    _log(stt, f"imported {len(holds)} holds + {len(seqs)} stretches; track V{k2 + 1}")
    _save(stt)
    return None


def _clips(p):
    fold = _mp_folder(p.GetMediaPool(), create=False)
    holds, seqs = {}, {}
    for c in fold.GetClipList() or []:
        n = c.GetClipProperty("File Name") or ""
        if n.startswith("hold-"):
            holds[int(n[5:12])] = c
        elif n[:1] == "d":
            seqs[int(n[1:8])] = c
    return holds, seqs


def _append(mp, infos, what):
    got = mp.AppendToTimeline(infos) or []
    if len(got) != len(infos):
        raise RuntimeError(f"placed {len(got)} of {len(infos)} {what}")
    return got


def _place(p, tl, stt, end):
    mp = p.GetMediaPool()
    if p.GetCurrentTimeline().GetName() != tl.GetName():
        p.SetCurrentTimeline(tl)
    holds, seqs = _clips(p)
    K, runs = stt["K"], stt["runs"]
    if stt["stage"] == "place_d":                     # animated stretches: exact lengths
        ds = [r for r in runs if r[0] == "D"]
        while stt["i"] < len(ds) and time.time() < end:
            batch = ds[stt["i"]:stt["i"] + 40]
            infos = []
            for k, a, b in batch:
                c = seqs[a]
                s0 = int(c.GetClipProperty("Start"))
                infos.append({"mediaPoolItem": c, "startFrame": s0, "endFrame": s0 + (b - a), "trackIndex": K,
                              "recordFrame": _m(stt, a), "mediaType": 1})
            _append(mp, infos, "animated stretches")
            stt["i"] += len(batch)
        if stt["i"] < len(ds):
            _save(stt); return f"placing the pictures ({stt['i']}/{len(ds)} stretches)"
        # a 1-frame blocker right after the end, so the last hold can't run past it
        c = seqs[ds[0][1]]; s0 = int(c.GetClipProperty("Start"))
        _append(mp, [{"mediaPoolItem": c, "startFrame": s0, "endFrame": s0 + 1, "trackIndex": K,
                      "recordFrame": _m(stt, stt["B"]), "mediaType": 1}], "end marker")
        stt["stage"] = "place_s"; stt["i"] = 0
        # right to left: a piece appended in front of an existing clip is trimmed to the gap
        # (Resolve stills are always 300 frames), so everything to its right must be there first
        chunks = []
        for k, a, b in reversed(runs):
            if k == "S":
                n, r = divmod(b - a, 300)
                if r:
                    chunks.append([a, a + 300 * n, False])
                for j in range(n - 1, -1, -1):
                    chunks.append([a, a + 300 * j, True])
        stt["chunks"] = chunks
        _save(stt)
    if stt["stage"] == "place_s":                     # holds: stills are always 300 frames long
        ch = stt["chunks"]
        while stt["i"] < len(ch) and time.time() < end:
            a, f, full = ch[stt["i"]]
            if full:                                  # whole 300-frame pieces: several at once
                batch = []
                while stt["i"] < len(ch) and ch[stt["i"]][2] and len(batch) < 40:
                    a, f, _ = ch[stt["i"]]
                    batch.append({"mediaPoolItem": holds[a], "startFrame": 0, "endFrame": 300, "trackIndex": K,
                                  "recordFrame": _m(stt, f), "mediaType": 1})
                    stt["i"] += 1
                _append(mp, batch, "hold pieces")
            else:                                     # the remainder: trimmed to the gap
                _append(mp, [{"mediaPoolItem": holds[a], "startFrame": 0, "endFrame": 300, "trackIndex": K,
                              "recordFrame": _m(stt, f), "mediaType": 1}], "hold ends")
                stt["i"] += 1
        if stt["i"] < len(ch):
            _save(stt); return f"placing the pictures ({stt['i']}/{len(ch)} hold pieces)"
        # repair pass: Resolve occasionally drops a piece (seen once: the very first hold's end);
        # fill any gap from its own run (with both neighbours present the fill is trimmed exactly)
        import bisect
        starts = [_m(stt, a) for k, a, b in runs]
        stt["repaired"] = []
        for _ in range(3):
            its = sorted((i.GetStart(), i.GetEnd()) for i in tl.GetItemListInTrack("video", K) or [])
            edge = [(_m(stt, stt["A"]), _m(stt, stt["A"]))] + its
            gaps = [(x[1], y[0]) for x, y in zip(edge, edge[1:]) if y[0] > x[1]]
            if not gaps:
                break
            for g0, g1 in gaps:
                k, a, b = runs[bisect.bisect_right(starts, g0) - 1]
                if k == "S":
                    info = {"mediaPoolItem": holds[a], "startFrame": 0, "endFrame": 300}
                else:
                    c = seqs[a]; s0 = int(c.GetClipProperty("Start")) + (g0 - _m(stt, a))
                    info = {"mediaPoolItem": c, "startFrame": s0, "endFrame": s0 + min(g1, _m(stt, b)) - g0}
                info.update({"trackIndex": K, "recordFrame": g0, "mediaType": 1})
                mp.AppendToTimeline([info])
                stt["repaired"].append([g0, g1, k])
        if stt["repaired"]:
            _log(stt, f"repaired gaps: {stt['repaired'][:10]}")
        items = tl.GetItemListInTrack("video", K) or []
        blk = [it for it in items if it.GetStart() == _m(stt, stt["B"])]
        if blk and not tl.DeleteClips(blk):
            raise RuntimeError("couldn't remove the end marker")
        stt["stage"] = "position" if stt.get("strip") else "verify"; stt["i"] = 0
        _log(stt, "placed")
        _save(stt)
    if stt["stage"] == "position":                    # strip pictures: tilt each piece down onto the board's rows
        items = sorted(tl.GetItemListInTrack("video", K) or [], key=lambda i: i.GetStart())
        tv = float(stt["strip"]["place_tilt"])
        while stt["i"] < len(items) and time.time() < end:
            if not items[stt["i"]].SetProperty("Tilt", tv):
                raise RuntimeError(f"couldn't position strip piece {stt['i']}")
            stt["i"] += 1
        if stt["i"] < len(items):
            _save(stt); return f"positioning the pictures ({stt['i']}/{len(items)})"
        bad = [i.GetStart() for i in items if abs(float(i.GetProperty("Tilt") or 0) - tv) > 0.01]
        if bad:
            raise RuntimeError(f"{len(bad)} strip pieces not positioned (first at {bad[0]})")
        stt["stage"] = "verify"
        _log(stt, f"positioned {len(items)} strip pieces (tilt {tv:.0f})")
        _save(stt)
    return None


def _verify(p, tl, stt):
    K, T0 = stt["K"], stt["T0s"]
    items = sorted(tl.GetItemListInTrack("video", K) or [], key=lambda i: i.GetStart())
    if not items:
        raise RuntimeError("nothing on the stills track")
    lo, hi = _m(stt, stt["A"]), _m(stt, stt["B"])
    if items[0].GetStart() != lo or items[-1].GetEnd() != hi:
        raise RuntimeError(f"stills cover {items[0].GetStart()}-{items[-1].GetEnd()}, scoreboard is {lo}-{hi}")
    for x, y in zip(items, items[1:]):
        if x.GetEnd() != y.GetStart():
            raise RuntimeError(f"gap/overlap on the stills track at frame {x.GetEnd()} vs {y.GetStart()}")
    # every frame shows the right picture
    run_at = {}
    for k, a, b in stt["runs"]:
        run_at[_m(stt, a)] = (k, a, b)
    bounds = sorted(run_at)
    import bisect
    for it in items:
        s = it.GetStart()
        k, a, b = run_at[bounds[bisect.bisect_right(bounds, s) - 1]]
        if it.GetEnd() > _m(stt, b):
            raise RuntimeError(f"a piece at {s} runs past its stretch ({it.GetEnd()} > {_m(stt, b)})")
        n = it.GetName() or ""
        if k == "S" and n != f"hold-{a:07d}-x{EXT}":
            raise RuntimeError(f"wrong picture at {s}: {n}")
        if k == "D":
            if not n.startswith(_name(k, a)):
                raise RuntimeError(f"wrong stretch at {s}: {n}")
            src = int(it.GetMediaPoolItem().GetClipProperty("Start")) + it.GetLeftOffset()
            if src != T0 + a + (s - _m(stt, a)):
                raise RuntimeError(f"stretch at {s} starts on the wrong picture ({src} vs {T0 + a + s - _m(stt, a)})")
    stt["items"] = len(items)
    stt["stage"] = "check"; stt["ci"] = 0
    # what to re-check: the last frame of a few holds (the analysis says nothing changes there)
    S = [r for r in stt["runs"] if r[0] == "S"]
    rnd = random.Random(stt["started"])
    pick = sorted(S, key=lambda r: r[1] - r[2])[:4] + rnd.sample(S, min(6, len(S)))
    stt["checks"] = [[a, b - 1] for k, a, b in pick] + [[a, rnd.randrange(a, b)] for k, a, b in rnd.sample(S, min(2, len(S)))]
    d = [r for r in stt["runs"] if r[0] == "D" and r[2] - r[1] > 2]
    stt["comp_check"] = [rnd.choice(S)[1] + 1, (lambda r: (r[1] + r[2]) // 2)(rnd.choice(d)) if d else None]
    _log(stt, f"verified {len(items)} pieces")
    _save(stt)


def _check(p, tl, stt, end):
    cdir = os.path.join(stt["run_dir"], "check")
    os.makedirs(cdir, exist_ok=True)
    T0 = stt["T0s"]
    sbt = _timeline(p, "Scoreboard")
    while stt["ci"] < len(stt["checks"]) and time.time() < end - 8:
        a, f = stt["checks"][stt["ci"]]
        if p.GetCurrentTimeline().GetName() != "Scoreboard":
            p.SetCurrentTimeline(sbt)
        got = _render_one(p, T0 + f, cdir, f"chk{f:07d}x", True, FMT, CODEC)
        if not got:
            raise RuntimeError(f"check render of frame {f} failed")
        sp = stt.get("strip")
        pair = [got, os.path.join(stt["run_dir"], f"hold-{a:07d}-x{EXT}"), "rgba64le"] + ([sp["y0"], sp["h"]] if sp else [])
        r = _compare(stt, [pair])[0]
        if r is None or r[0] > 1.0:
            raise RuntimeError(f"the scoreboard changes inside a hold (comp frame {f}, diff {r}) — analysis missed something")
        if sp and r[2] > 0:
            raise RuntimeError(f"the board reaches outside the strip at comp frame {f} — strip too small")
        stt["ci"] += 1
        _save(stt)
    if stt["ci"] < len(stt["checks"]):
        return "checking the pictures"
    # the whole frame: live scoreboard vs pictures, at a hold and inside an animation
    if p.GetCurrentTimeline().GetName() != tl.GetName():
        p.SetCurrentTimeline(tl)
    K = stt["K"]
    it2 = _sb_items(tl)[0][1]
    res = []
    for f in [x for x in stt["comp_check"] if x is not None]:
        m = _m(stt, f)
        its = [i for i in tl.GetItemListInTrack("video", K) or [] if i.GetStart() <= m < i.GetEnd()]
        if len(its) != 1:
            raise RuntimeError(f"no single picture at frame {m}")
        it2.SetClipEnabled(True); its[0].SetClipEnabled(False)
        ref = _render_one(p, m, cdir, f"live{m}x", False, "tif", "RGB16")
        it2.SetClipEnabled(False); its[0].SetClipEnabled(True)
        new = _render_one(p, m, cdir, f"pics{m}x", False, "tif", "RGB16")
        if not its[0].GetClipEnabled() or it2.GetClipEnabled():
            raise RuntimeError("clip switches didn't take")
        r = _compare(stt, [[ref, new, "rgb48le"]])[0] if ref and new else None
        res.append(r)
        for x in (ref, new):
            try:
                os.remove(x)
            except Exception:
                pass
        if r is None or r[0] > 1.0:
            raise RuntimeError(f"whole-frame check at {m} differs from the live scoreboard ({r})")
    stt["comp_result"] = res
    # done: live scoreboard clip off (the stills track takes over), save
    it2.SetClipEnabled(False)
    if it2.GetClipEnabled():
        raise RuntimeError("couldn't switch the live scoreboard clip off")
    p.DeleteAllRenderJobs()
    resolve.GetProjectManager().SaveProject()    # noqa: F821
    stt["stage"] = "ready"; stt["ready_at"] = time.time()
    _log(stt, f"READY — checks ok, whole-frame {res}")
    _save(stt)
    return None


def step(p, tl, folder, end):
    """One slice of the build. -> {"state": "waiting"|"ready"|"live"|"error", "msg", "retry_s"}"""
    stt = _load(folder, p.GetName())
    # a build that failed moments ago (e.g. while drawing ahead during the picture wait) is not
    # retried for the same export: that export just runs with the live scoreboard
    if (stt and stt.get("stage") == "failed" and not stt.get("consumed")
            and time.time() - stt.get("touched", 0) < 30 * 60):
        return {"state": "live", "msg": f"scoreboard stills skipped ({stt.get('reason')}) — exporting with the live scoreboard"}
    try:
        if (not stt or stt.get("consumed") or stt.get("stage") == "failed" or stt.get("tl") != tl.GetName()
                or (stt.get("stage") != "ready" and time.time() - stt.get("touched", 0) > STALE_MIN * 60)):
            stt = _fresh(p, tl, folder)
            return {"state": "waiting", "retry_s": 3,
                    "msg": f"scoreboard stills: plan ready ({sum(1 for r in stt['runs'] if r[0] == 'S')} holds, "
                           f"{sum(r[2] - r[1] for r in stt['runs'] if r[0] == 'D')} animated frames)"}
        if time.time() - stt["started"] > MAX_BUILD_MIN * 60:
            raise RuntimeError(f"took longer than {MAX_BUILD_MIN} min")
        st_ = stt["stage"]
        msg = None
        if st_ == "queue":
            _queue(p, stt, end); msg = f"queued {stt['queued']}/{len(stt['runs'])} picture jobs"
        elif st_ == "render":
            msg = _render_wait(p, stt)
            if msg:
                return {"state": "waiting", "retry_s": 15, "msg": "scoreboard stills: " + msg}
        elif st_ == "import":
            msg = _import(p, tl, stt, end)
        elif st_ in ("place_d", "place_s", "position"):
            msg = _place(p, tl, stt, end)
        elif st_ == "verify":
            _verify(p, tl, stt); msg = "checking"
        elif st_ == "check":
            msg = _check(p, tl, stt, end)
        if stt["stage"] == "ready":
            mins = (stt["ready_at"] - stt["started"]) / 60
            return {"state": "ready", "msg": f"scoreboard stills ready in {mins:.0f} min "
                    f"({stt['items']} pieces, all frames covered, checks identical) — exporting without the live scoreboard"}
        return {"state": "waiting", "retry_s": 2, "msg": "scoreboard stills: " + (msg or stt["stage"])}
    except Exception as e:
        reason = str(e)[:300]
        try:
            if stt:
                stt["stage"] = "failed"; stt["reason"] = reason
                _log(stt, "FAILED: " + reason)
                _save(stt)
            p.DeleteAllRenderJobs()
            restore(p, tl)
            if p.GetCurrentTimeline().GetName() != tl.GetName():
                p.SetCurrentTimeline(tl)
        except Exception as e2:
            return {"state": "error", "msg": f"scoreboard stills failed ({reason}) and couldn't be undone: {e2}"}
        return {"state": "live", "msg": f"scoreboard stills skipped ({reason}) — exporting with the live scoreboard"}


def building(p, folder):
    """True while a build for this project is under way (its render jobs are ours, not an export)"""
    stt = _load(folder, p.GetName())
    return bool(stt and not stt.get("consumed") and stt.get("stage") not in ("ready", "failed")
                and time.time() - stt.get("touched", 0) < STALE_MIN * 60)


def consume(p, folder, used):
    stt = _load(folder, p.GetName())
    if stt:
        stt["consumed"] = True; stt["used"] = used
        _save(stt)
