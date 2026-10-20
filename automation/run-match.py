"""
run-match.py — hands-off match chain (2026-10-07, Kenny approved the idea).

Runs the whole "start the volleyball workflow" chain on the PC without Claude
checking in between steps: card copy -> setup -> finish (waits by itself) ->
export -> small approval images. Each step starts the moment the previous one
ends. Same scripts, same settings, same results as running the phases one by one.

    PY run-match.py [--recent] [--folder "<match folder>"] [--event "YRV 15U Tournament" | --ask-event]
                    [--offset N] [--tavo] [--hold-export] [--project "zz ..."] [--export-name "zz ..."]

  --ask-event    (2026-10-08) Claude asked Kenny for the event while the card copies; his
                 answer arrives as event-pending.txt (written after this run started; "none"
                 = no event). Waited for up to 10 min before setup, then it goes on without.

Early picture check (2026-10-08, every match): ~1 min after the start it grabs one frame from
the card (or --folder) and writes _overlay_check\picture-check.jpg (4 options; status line
"PICTURE CHECK READY"). Kenny's answer arrives as picture-pending.txt ("1".."4", optionally
"bottom"/"centre", or "z=1.08 s=1.04 p=0.90 a=top"); it's applied to the V1 camera clips just
before the export. No answer 10 min after finish -> option 1 (as filmed). --no-picture-check skips it.

2026-10-08 additions: after finish it picks the thumbnail itself (prep-upload thumbnail auto)
and puts review sheet + thumbnail + YouTube text into _overlay_check\approval\; after the
export starts it measures the real render speed (~6 min in) for the finish time; and it
writes run-summary.txt (flags, event, TAVO, files, finish time) for Claude to read.

  --offset N     (2026-10-14) the camera was already recording N s before START was tapped (positive =
                 camera early). Writes "offset": N into THIS match folder's copy of the scorekeeper .json
                 only (never the original on Google Drive) before setup. Without --offset, if copy-card
                 measured a camera-vs-START gap of more than 3 s, the run says so (status line "OFFSET
                 SUGGESTED" + offset-suggestion.txt, same ~1 min as the picture check) and Claude asks
                 Kenny; his answer arrives as offset-pending.txt ("yes" / a number / "no"), waited for up
                 to 10 min only if Claude wrote offset-asked.txt. Nothing is applied without --offset or a "yes";
                 otherwise run-summary.txt gets a FLAG line with the suggested --offset.
  --folder       skip the card copy and use this match folder (re-runs, tests)
  --hold-export  stop after finish (picture check first); export later by phase
  --project / --export-name   test names (Thundercats folder only, "zz ...")

Talks to Resolve through Resolve Studio's own external scripting (Resolve must be
open and started by Kenny, not by the Claude app — checked). Never starts Resolve.

Status: run-match-status.txt (one line per step). The last line is one of
  RUN READY FOR APPROVAL ...   (approval images ready; export end ESTIMATED — 2026-10-19: sent before the export starts)
  EXPORT RUNNING ...           (export started; measured finish time)
  RUN READY FOR PICTURE CHECK  (--hold-export)
  RUN STOPPED: <reason>        (nothing after the failed step was done)
Full phase results: run-match-result.json. Phase logs still go to prepare-log.txt.
"""
import argparse, json, os, subprocess, sys, time, traceback

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
PY = r"C:\Python314\python.exe"
OC = W + r"\_overlay_check"
STATUS = W + r"\run-match-status.txt"
RESULT = W + r"\run-match-result.json"
SUMMARY = W + r"\run-summary.txt"
PENDING = W + r"\event-pending.txt"
PIC_PENDING = W + r"\picture-pending.txt"
PIC_OUT = W + r"\_overlay_check\picture-check.jpg"
PIC_OPTIONS = {1: ("as filmed", 1.00, 1.00, 1.00), 2: ("brighter", 1.00, 1.06, 0.85),
               3: ("brighter + zoom 5%", 1.05, 1.06, 0.85), 4: ("brighter + zoom 10%", 1.10, 1.06, 0.85)}
T_START = time.time()
NOWIN = 0x08000000
UTF8 = dict(os.environ, PYTHONIOENCODING="utf-8")
results = {}
sys.path.insert(0, W)
import offset_tools as ot                     # 2026-10-14: camera-start offset (see --offset)
OFF_PENDING = W + r"\offset-pending.txt"
OFF_ASKED = W + r"\offset-asked.txt"
OFF_SUGGEST = W + r"\offset-suggestion.txt"


def st(msg, first=False):
    with open(STATUS, "w" if first else "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def save():
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, ensure_ascii=False, default=str)


def make_picture_check(clip):
    try:
        r = subprocess.run([PY, W + r"\make-picture-check.py", clip, PIC_OUT], cwd=W, env=UTF8,
                           capture_output=True, text=True, timeout=120, creationflags=NOWIN)
        line = [l for l in r.stdout.splitlines() if l.startswith("PICTURE CHECK:")]
        results["picture_check"] = line[0] if line else "FAILED " + (r.stdout + r.stderr)[-300:]
        if line:
            st("PICTURE CHECK READY: " + PIC_OUT)
    except Exception as e:
        results["picture_check"] = "FAILED " + repr(e)


def parse_choice(txt):
    """'3', '4 bottom', 'z=1.08 s=1.04 p=0.9 a=top' -> (label, zoom, slope, power, anchor)"""
    t = txt.strip().lower()
    anchor = "bottom" if "bottom" in t else ("centre" if ("centre" in t or "center" in t) else "top")
    kv = dict(x.split("=", 1) for x in t.replace(",", " ").split() if "=" in x)
    if kv:
        z, sl, pw = float(kv.get("z", 1)), float(kv.get("s", 1)), float(kv.get("p", 1))
        anchor = {"b": "bottom", "c": "centre"}.get(kv.get("a", "t")[:1], "top")
        return (f"custom zoom {z} slope {sl} power {pw}", z, sl, pw, anchor)
    for ch in t:
        if ch.isdigit() and int(ch) in PIC_OPTIONS:
            label, z, sl, pw = PIC_OPTIONS[int(ch)]
            return (f"option {ch}: {label}", z, sl, pw, anchor)
    return ("option 1: as filmed (answer not understood: " + txt[:40] + ")",) + PIC_OPTIONS[1][1:] + ("top",)


def apply_picture(r, choice):
    """zoom / framing / brightness on the V1 camera clips of the Match timeline (notes: per-match tweaks)"""
    label, z, sl, pw, anchor = choice
    if z == 1 and sl == 1 and pw == 1:
        return label + " — nothing to change"
    p = r.GetProjectManager().GetCurrentProject()
    tl = None
    for i in range(1, p.GetTimelineCount() + 1):
        x = p.GetTimelineByIndex(i)
        if x.GetName().startswith("Match"):
            tl = x; break
    if not tl:
        raise RuntimeError("no Match timeline")
    p.SetCurrentTimeline(tl)
    tilt = {"top": -1, "bottom": 1, "centre": 0}[anchor] * (z - 1) * 1080
    items = tl.GetItemListInTrack("video", 1) or []
    r.OpenPage("color")
    ok = 0
    for it in items:
        a1 = it.SetProperty("ZoomX", z) and it.SetProperty("ZoomY", z) and it.SetProperty("Tilt", tilt)
        a2 = True
        if sl != 1 or pw != 1:
            a2 = it.SetCDL({"NodeIndex": "1", "Slope": f"{sl} {sl} {sl}", "Offset": "0 0 0",
                            "Power": f"{pw} {pw} {pw}", "Saturation": "1.0"})
        ok += bool(a1 and a2)
    r.OpenPage("edit")
    r.GetProjectManager().SaveProject()
    chk = items[0].GetProperty("ZoomX") if items else None
    if ok != len(items) or not items:
        raise RuntimeError(f"applied to {ok} of {len(items)} clips")
    return f"{label}, {anchor} edge kept — applied to {ok} camera clips (ZoomX now {chk}, Tilt {tilt:.0f})"


def summary(extra=()):
    keys = ("project:", "FLAG", "***", "event:", "set breaks", "time-out", "TAVO", "missing", "ERROR")
    lines = []
    for ph in ("setup", "finish", "export"):
        for res in results.get(ph, [])[-1:]:
            for l in res.get("log") or []:
                if any(k in l for k in keys) and l not in lines:
                    lines.append(l)
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(list(extra) + results.get("offset_lines", []) + lines) + "\n")


def stop(reason):
    save()
    try:
        summary(["RUN STOPPED: " + reason])
    except Exception:
        pass
    st("RUN STOPPED: " + reason)
    sys.exit(1)


def connect():
    sys.path.append(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    try:
        import DaVinciResolveScript as d
        r = d.scriptapp("Resolve")
    except Exception as e:
        r = None
        results["connect_error"] = repr(e)
    if not r:
        stop("can't reach Resolve — is it open? (Preferences > System > General > External scripting = Local)")
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "$p=Get-CimInstance Win32_Process -Filter \"Name='Resolve.exe'\" | Select -First 1;"
                         "(Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.ParentProcessId)\").Name"],
                        capture_output=True, text=True, timeout=30, creationflags=NOWIN)
    parent = ps.stdout.strip().lower()
    results["resolve_parent"] = parent
    if "claude" in parent:
        stop("Resolve was started by the Claude app — Kenny: save, close and reopen Resolve from the Start menu")
    return r


SRC = None
def phase(r, name, a, folder):
    global SRC
    if SRC is None:
        SRC = open(W + r"\prepare-match.py", encoding="utf-8").read()
    g = {"resolve": r, "PM_PHASE": name, "PM_FOLDER": folder, "__name__": "pm"}
    if a.event: g["PM_EVENT"] = a.event
    if a.tavo: g["PM_TAVO"] = True
    if a.project: g["PM_PROJECT"] = a.project
    if a.export_name: g["PM_EXPORT_NAME"] = a.export_name
    if getattr(a, "live_scoreboard", False): g["PM_LIVE_SCOREBOARD"] = True
    try:
        exec(SRC, g)
    except SystemExit:
        pass
    except Exception:
        results[name + "_error"] = traceback.format_exc()[-1500:]
        stop(f"{name} crashed — see run-match-result.json")
    res = g.get("result") or {}
    results.setdefault(name, []).append(res)
    save()
    return res


def export_waiting(r, a, folder, say_fn):
    """2026-10-19: the export phase answers "waiting" while the TAVO file encodes (retry in 60 s)
    and while the scoreboard pictures are drawn (retry in a few s); progress -> status every ~2 min."""
    res = phase(r, "export", a, folder)
    t0 = t_said = time.time()
    while res.get("waiting") and time.time() - t0 < 100 * 60:
        if len(results.get("export", [])) > 4:
            results["export"] = results["export"][-4:]
        if time.time() - t_said > 120:
            say_fn(last(res)); t_said = time.time()
        time.sleep(res.get("retry_s", 60))
        res = phase(r, "export", a, folder)
    return res


def last(res):
    lg = res.get("log") or []
    return lg[-1] if lg else str(res)[:200]


def shrink(src, dst, width=None, scale=None):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w = width or int(im.width * scale)
    im.resize((w, round(im.height * w / im.width)), Image.LANCZOS).save(dst, quality=85)
    return dst


def announce_offset(dest):
    """2026-10-14: as soon as copy-card has measured the camera-vs-START gap (or from the folder's
    copy-info.txt), say so — status line + offset-suggestion.txt — so Claude can ask Kenny in the first
    message. Nothing is applied here."""
    try:
        sg = ot.suggest(dest)
    except Exception as e:
        results["offset_error"] = repr(e)
        return None
    if sg:
        sg["folder"] = dest
        with open(OFF_SUGGEST, "w", encoding="utf-8") as f:
            json.dump(sg, f)
        results["offset_suggestion"] = sg
        st(f"OFFSET SUGGESTED: {sg['text']} (measured gap {sg['gap']:+.0f} s) -> suggest --offset {ot.fmt(sg['offset'])}; "
           "answer goes in offset-pending.txt (yes / a number / no)")
        save()
    return sg


def resolve_offset(a, folder):
    """Put the camera-start offset into THIS folder's .json copy (never the Drive original).
    --offset N wins; otherwise a measured gap > 3 s is applied only if Kenny said yes."""
    fresh = lambda f: os.path.exists(f) and os.path.getmtime(f) >= T_START - 5
    val, how = None, None
    sg = results.get("offset_suggestion") or ot.suggest(folder)
    if a.offset is not None:
        val, how = a.offset, f"--offset {ot.fmt(a.offset)}"
    elif sg:
        if fresh(OFF_ASKED) or fresh(OFF_PENDING):
            txt = None
            for i in range(41):
                if fresh(OFF_PENDING):
                    txt = open(OFF_PENDING, encoding="utf-8").read()
                    break
                if i == 0:
                    st("waiting for the offset answer (offset-pending.txt) …")
                if i < 40:
                    time.sleep(15)
            val, note = ot.parse_answer(txt, sg)
            how = "Kenny: " + note
        else:
            how = "not asked"
        if val is None:
            results["offset_lines"] = [f"FLAG: {sg['text']} (gap {sg['gap']:+.0f} s) — suggested --offset "
                                       f"{ot.fmt(sg['offset'])} NOT applied ({how}); scores may show up early/late by about that much"]
            st("offset: not applied (" + how + ")")
            save()
            return
    else:
        return
    try:
        j, old = ot.write_offset(folder, val)
    except Exception as e:
        results["offset_lines"] = [f"FLAG: offset {ot.fmt(val)} s could NOT be written — {e!r}"]
        stop("offset couldn't be written into the match folder's .json — " + repr(e)[:150])
    results["offset"] = {"value": val, "how": how, "file": j, "old": old}
    results["offset_lines"] = [f"offset: {ot.fmt(val)} s applied to the scores in this match folder's {os.path.basename(j)} "
                               f"({how}; was {ot.fmt(old) if old is not None else 'none'}); the Google Drive original is untouched"]
    st("offset: " + results["offset_lines"][0][8:])
    save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", action="store_true")
    ap.add_argument("--folder"); ap.add_argument("--event"); ap.add_argument("--tavo", action="store_true")
    ap.add_argument("--hold-export", action="store_true")
    ap.add_argument("--ask-event", action="store_true")
    ap.add_argument("--no-picture-check", action="store_true")
    ap.add_argument("--project"); ap.add_argument("--export-name")
    ap.add_argument("--live-scoreboard", action="store_true")   # 2026-10-19: skip the scoreboard pictures
    ap.add_argument("--offset", type=float)      # seconds the camera started before START (positive = early)
    a = ap.parse_args()
    st("RUN STARTED " + " ".join(sys.argv[1:]), first=True)
    # tests ("zz" project) never write the YouTube text / thumbnail into the match folder
    # (2026-10-08: a test overwrote the Thundercats folder's own thumbnail.jpg)
    # 2026-10-14 test guard: a zz (test) project runs only on a zz folder, and a test run
    # (VENOM_TEST=1, set by zz-test.py) only as a zz project — never on a real match folder
    test = (a.project or "").lower().startswith("zz") or os.environ.get("VENOM_TEST") == "1"
    if test and not (a.folder and os.path.basename(a.folder.rstrip("\\")).lower().startswith("zz")
                     and (a.project or "").lower().startswith("zz")):
        stop("test runs need a zz project AND a zz folder (--project \"zz …\" --folder \"…\\zz …\")")
    if test:
        os.environ.setdefault("PREP_OUT", OC + r"\zz-test-out")
        os.makedirs(os.environ["PREP_OUT"], exist_ok=True)
    results["args"] = vars(a)
    try:
        os.remove(OFF_SUGGEST)                   # never leave an older run's suggestion behind
    except OSError:
        pass

    # 1. card copy (Resolve isn't needed yet, so Kenny can still open it meanwhile)
    folder = a.folder
    if not folder:
        st("copying the card …")
        cp = subprocess.Popen([PY, W + r"\copy-card.py", "--recent" if a.recent else "--latest"],
                              cwd=W, env=UTF8, creationflags=NOWIN)
        src_list = W + r"\copy-sources.txt"
        pic_done = a.no_picture_check
        off_done = False
        while cp.poll() is None:                     # early picture check from the card (2026-10-08)
            if not off_done and a.offset is None and os.path.exists(src_list) and os.path.getmtime(src_list) >= T_START - 5:
                try:                                  # 2026-10-14: gap is known as soon as the copy starts
                    announce_offset(json.load(open(src_list, encoding="utf-8"))["dest"])
                except Exception as e:
                    results["offset_error"] = repr(e)
                off_done = True
            if not pic_done and os.path.exists(src_list) and os.path.getmtime(src_list) >= T_START - 5:
                try:
                    fl = json.load(open(src_list, encoding="utf-8"))["files"]
                    make_picture_check(fl[0] if len(fl) == 1 else max(fl[:2], key=os.path.getsize))
                except Exception as e:
                    results["picture_check"] = "FAILED " + repr(e)
                pic_done = True
            time.sleep(5)
        tail = open(W + r"\copy-card-log.txt", encoding="utf-8").read().strip().splitlines()[-1]
        results["copy"] = tail
        if "COPY OK" not in tail:
            stop("card copy: " + tail[9:])
        folder = tail.split(" — ")[-1].strip()
        st("copy ok: " + folder)
    elif not a.no_picture_check:
        import glob
        clips = sorted(glob.glob(os.path.join(folder, "DJI_*.MP4")))
        if clips:
            make_picture_check(clips[0] if len(clips) == 1 else max(clips[:2], key=os.path.getsize))

    # 1b. camera-start offset into this match folder's .json copy (2026-10-14)
    if a.offset is None and not results.get("offset_suggestion"):
        announce_offset(folder)                      # --folder runs / copies too fast for the loop above
    resolve_offset(a, folder)

    # 2. Resolve (wait up to 10 min for Kenny to open it)
    sys.path.append(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    for i in range(20):
        try:
            import DaVinciResolveScript as d
            if d.scriptapp("Resolve"):
                break
        except Exception:
            pass
        if i == 0:
            st("waiting for Resolve to be opened …")
        time.sleep(30)
    r = connect()

    # 2b. event name Kenny gave after the start (2026-10-08)
    if a.ask_event and not a.event:
        for i in range(40):
            if os.path.exists(PENDING) and os.path.getmtime(PENDING) >= T_START - 5:
                ev = open(PENDING, encoding="utf-8").read().strip()
                a.event = None if ev.lower() in ("", "none", "no", "-") else ev
                results["event_pending"] = ev
                break
            if i == 0:
                st("waiting for the event name (event-pending.txt) …")
            time.sleep(15)
        else:
            results["event_pending"] = "no answer in 10 min — went on without an event"
        st("event: " + (a.event or "none"))

    # 3. setup
    res = phase(r, "setup", a, folder)
    st("setup: " + last(res))
    if not res.get("ok"):
        stop("setup had problems — see run-match-result.json")

    # 4. finish (waits for the background clips by itself)
    time.sleep(200)
    for i in range(30):
        res = phase(r, "finish", a, folder)
        if not res.get("waiting"):
            break
        time.sleep(45)
    st("finish: " + last(res))
    if not res.get("ok"):
        stop("finish had problems — see run-match-result.json")
    sheet, contact = res.get("sheet"), res.get("thumb_contact")

    # 5. approval images, small (made before the export so they're ready either way)
    small = OC + r"\approval-small"
    os.makedirs(small, exist_ok=True)
    try:
        if sheet and os.path.exists(sheet):
            results["sheet_small"] = shrink(sheet, small + r"\review-sheet-small.jpg", scale=0.35)
        if contact and os.path.exists(contact):
            results["contact_small"] = shrink(contact, small + r"\contact-small.jpg", width=960)
    except Exception as e:
        results["shrink_error"] = repr(e)
    # 5b. thumbnail (auto-picked) + approval kit (2026-10-08)
    try:
        info = json.load(open(W + r"\youtube-info.json", encoding="utf-8"))
        base = f'{info["date"]} {info["team1"]} vs {info["team2"]}'
        cand = OC + r"\thumb-candidates\cand.json"
        for i in range(24):                          # candidates finish in the background
            if os.path.exists(cand):
                break
            time.sleep(5)
        target = os.path.join(os.environ.get("PREP_OUT") or os.path.dirname(info["matchFile"]),
                              base + " - thumbnail.jpg")
        if a.folder and os.path.exists(target):       # re-run: never replace a thumbnail already made
            th = [target]
            tr = subprocess.CompletedProcess([], 0, "THUMBNAIL kept (already there): " + target, "")
        else:
            tr = subprocess.run([PY, W + r"\prep-upload.py", "thumbnail", "auto"], cwd=W,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                capture_output=True, text=True, timeout=180, creationflags=NOWIN)
            th = [l[11:].rsplit(" (candidate", 1)[0] for l in tr.stdout.splitlines() if l.startswith("THUMBNAIL: ")]
        results["thumbnail"] = th[0] if th else "FAILED " + (tr.stdout + tr.stderr)[-300:]
        appr = OC + r"\approval"
        os.makedirs(appr, exist_ok=True)
        import shutil
        kit = []
        for src in (sheet, th[0] if th else None, res.get("youtube_text")):
            if src and os.path.exists(src):
                shutil.copy2(src, appr); kit.append(appr + "\\" + os.path.basename(src))
        results["approval_kit"] = kit
        results["thumb_pick"] = [l for l in tr.stdout.splitlines() if l.startswith("THUMBNAIL")]
    except Exception as e:
        results["kit_error"] = repr(e)
    save()

    if a.hold_export:
        # 2026-10-09 (tournament mode): the summary is written here too, so a held run has its flags
        summary([f"folder: {folder}", "thumbnail: " + str(results.get("thumbnail")),
                 "approval kit: " + " | ".join(results.get("approval_kit", [])),
                 "event: " + (a.event or "none") + "   TAVO: " + ("on" if a.tavo else "off"),
                 "export: not started (--hold-export)"])
        st("RUN READY FOR PICTURE CHECK (export not started)")
        return

    # 5b'. 2026-10-19 (Kenny "go"): the approval goes out NOW — the kit is ready — with an ESTIMATED
    # export end (scoreboard pictures ~1.5 + 0.12 min per video minute, then the export at ~0.6x the
    # video length; live scoreboard 0.95x; +5 min margin). The upload reminder re-checks export_status
    # and moves itself if the export runs long. The measured time follows as "EXPORT RUNNING".
    try:
        bj_ = json.load(open(W + r"\bookends.json", encoding="utf-8"))
        ps_ = json.load(open(W + r"\prepare-state.json", encoding="utf-8"))
        yi_ = json.load(open(W + r"\youtube-info.json", encoding="utf-8"))
        fr_ = (bj_["export_out"] - bj_["export_in"] + 1) - sum(c["in_frame"] - c["out_frame"] for c in bj_.get("cuts", []))
        mins_ = fr_ / 59.94 / 60
        try:
            live_ = a.live_scoreboard or open(W + r"\scoreboard-mode.txt", encoding="utf-8").read().strip().lower().startswith("live")
        except Exception:
            live_ = bool(a.live_scoreboard)
        est_min = (0 if live_ else 1.5 + 0.12 * mins_) + mins_ * (0.95 if live_ else 0.6) + 5
        e_ = time.time() + est_min * 60
        z_ = time.strftime("%z", time.localtime(e_))
        eta0, eta0_iso = time.strftime("%H:%M", time.localtime(e_)), time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(e_)) + z_[:3] + ":" + z_[3:]
        name_ = a.export_name or f'{yi_.get("date", ps_["date"])} {ps_["team1"]} vs {ps_["team2"]} - YouTube'
        file0 = os.path.join(folder, name_ + ".mp4")
        results.update({"eta_iso": eta0_iso, "eta_how": "estimate"})
        save()
        summary([f"folder: {folder}",
                 f"export: {file0}  done ~{eta0} (estimate: scoreboard pictures first, then the export; eta_iso {eta0_iso})",
                 "thumbnail: " + str(results.get("thumbnail")),
                 "approval kit: " + " | ".join(results.get("approval_kit", [])),
                 "event: " + (a.event or "none") + "   TAVO: " + ("on" if a.tavo else "off"),
                 "picture: chosen next (export after the picture choice)"])
        st(f"RUN READY FOR APPROVAL — export not started yet (scoreboard pictures first), estimated done ~{eta0} "
           f"({eta0_iso}, estimate); file {file0}")
    except Exception as e:
        results["early_approval_error"] = repr(e)

    # 5c. picture choice (2026-10-08): wait up to 10 min for Kenny's answer, else as filmed
    # waits only if Claude actually sent Kenny the picture (picture-asked.txt written after this
    # run started) — an older run sheet that never sends it exports as filmed with no 10-min wait
    asked = W + r"\picture-asked.txt"
    fresh = lambda f: os.path.exists(f) and os.path.getmtime(f) >= T_START - 5
    if not a.no_picture_check and (fresh(asked) or fresh(PIC_PENDING)):
        txt = None
        # 2026-10-19 (Kenny "go"): the scoreboard pictures are drawn during this wait (the picture
        # choice only changes the camera clips); the picture is applied once Resolve is free again
        sb = {"state": "waiting"}
        def sb_step():
            res_ = phase(r, "sb_prepare", a, folder)
            if len(results.get("sb_prepare", [])) > 4:
                results["sb_prepare"] = results["sb_prepare"][-4:]
            return res_
        t_wait = time.time()
        st("waiting for the picture choice (picture-pending.txt) — drawing the scoreboard pictures meanwhile …")
        while True:
            if os.path.exists(PIC_PENDING) and os.path.getmtime(PIC_PENDING) >= T_START - 5:
                txt = open(PIC_PENDING, encoding="utf-8").read(); break
            if time.time() - t_wait > 600:
                break
            t1 = time.time()
            if sb.get("state") in ("waiting", "busy"):
                sb = sb_step()
            time.sleep(max(1, min(15, sb.get("retry_s", 15)) - (time.time() - t1)))
        t2 = time.time()
        while sb.get("state") in ("waiting", "busy") and time.time() - t2 < 40 * 60:
            time.sleep(min(15, sb.get("retry_s", 5)))
            sb = sb_step()
        if sb.get("msg"):
            st(sb["msg"])
        choice = parse_choice(txt) if txt else ("option 1: as filmed (no answer in 10 min)",) + PIC_OPTIONS[1][1:] + ("top",)
        try:
            results["picture"] = apply_picture(r, choice)
        except Exception as e:
            results["picture"] = "FAILED " + repr(e)
            stop("picture tweak didn't apply — " + repr(e)[:150])
        st("picture: " + results["picture"])
        save()

    # 6. export
    res = export_waiting(r, a, folder, st)
    st("export: " + last(res))
    if not res.get("ok"):
        stop("export didn't start — see run-match-result.json")
    eta, eta_iso, how = res.get("eta"), res.get("eta_iso"), "estimate"
    st(f"export started, done ~{eta} (estimate) — measuring the real speed …")
    # 7. measure the real render speed (2026-10-08): ~6 min in (less for short tests)
    try:
        mins = res.get("frames", 0) / 59.94 / 60
        # 2026-10-19: with the scoreboard pictures the speed is steady, so 2 min is enough
        # (approval goes out ~4 min sooner); live scoreboard: as before
        cap = 120 if res.get("scoreboard") == "pictures" else 360
        time.sleep(max(60, min(cap, mins * 60 * 0.15)))
        ms = phase(r, "export_status", a, folder)
        if ms.get("eta_iso"):
            eta, eta_iso, how = ms["eta"], ms["eta_iso"], f"measured at {ms.get('percent')}%"
        elif ms.get("done"):
            eta, eta_iso, how = time.strftime("%H:%M"), None, "already finished: " + last(ms)
    except Exception as e:
        results["measure_error"] = repr(e)
    results["eta_iso"] = eta_iso
    save()
    summary([f"folder: {folder}",
             f"export: {res.get('file')}  done ~{eta} ({how}; eta_iso {eta_iso})",
             "thumbnail: " + str(results.get("thumbnail")),
             "approval kit: " + " | ".join(results.get("approval_kit", [])),
             "event: " + (a.event or "none") + "   TAVO: " + ("on" if a.tavo else "off"),
             "picture: " + str(results.get("picture", "check skipped"))])
    st(f"EXPORT RUNNING — done ~{eta} ({eta_iso}, {how}); file {res.get('file')}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        results["crash"] = traceback.format_exc()[-1500:]
        stop("run-match crashed — see run-match-result.json")
