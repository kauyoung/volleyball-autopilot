"""
Venom Rebels — prepare (and export) a match (2026-09-28, Kenny approved).

exec'd inside Resolve's scripting (Claude's run_script_unsafe), with `resolve`
defined and PM_PHASE set. EVERY call is kept well under the 60 s tool limit: slow
work runs in the background and the phases pick up where they left off — call
again while the result says "waiting".

  PM_PHASE = "setup"    (~15-30 s)
      match folder = PM_FOLDER, else the newest folder by date (Python, not Lua)
      + its scorekeeper .json (PM_JSON overrides)
      -> new project "<date> <HHMM> Venom vs <Opponent>" (PM_PROJECT overrides)
      -> assemble-match.lua with THAT folder passed in (MATCH_CLIP_FOLDER) — checked
      -> free-space check (YouTube + TAVO exports must fit on the drive)
      -> place-scoreboard.lua
      -> build + apply the scoreboard with THAT match file (SCOREBOARD_MATCH_FILE) — checked
      -> bake-static.lua, closes the "Render completed" pop-up
      -> make-bookends.py plan (+ flags)
      -> background: intro + summary clips, fix-audio, make-tavo, thumbnail choices
  PM_PHASE = "finish"   (~10-40 s per call; repeat while "waiting")
      -> audio swap, place-bookends (intro/summary, scoreboard fades, export range)
      -> review-sheet frames rendered in the YouTube preset (only the missing ones,
         never restarted), review sheet, YouTube text, thumbnail choices, TAVO status
      -> snapshot of this match's plan/state in <match folder>\\_workflow\\
  PM_PHASE = "export"         starts the YouTube export for the CURRENT project,
                              range + name from <match folder>\\_workflow\\ (free-space
                              check; waits if the TAVO file is still encoding —
                              PM_FORCE=True skips that wait)
  PM_PHASE = "export_status"  progress; when done: checks the file (frames, codecs)
  PM_PHASE = "sb_restore"     takes the scoreboard pictures off the Match timeline and
                              switches the live scoreboard back on (export_status and
                              finish do this by themselves; use it before hand edits)

Scoreboard pictures (2026-10-19, Kenny "go"): the export phase first draws the scoreboard
as pictures (scoreboard-stills.py, ~10 min for a full match, repeat while "waiting") and
exports with those instead of the live Fusion scoreboard: ~2.4x faster, no slowdown, same
look. Anything odd -> the live scoreboard, as before. Off: scoreboard-mode.txt = "live"
(every match) or PM_LIVE_SCOREBOARD=True / run-match --live-scoreboard (one run).

Each phase sets `result` (a dict) and appends to prepare-log.txt.
"""
import ctypes, ctypes.wintypes as wt, glob, json, os, re, shutil, subprocess, time

# No console windows for ffmpeg/ffprobe/python helpers on Windows (2026-10-01:
# every call used to flash a black window). Applies to all subprocess calls here.
if os.name == "nt" and not getattr(subprocess.Popen, "_no_window", False):
    class _NoWindowPopen(subprocess.Popen):
        _no_window = True
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _NoWindowPopen


W = r"C:\Users\YOURNAME\scoreboard-pipeline"
OC = W + r"\_overlay_check"
RDIR = OC + r"\review"
CAND = OC + r"\thumb-candidates"
PY = r"C:\Python314\python.exe"
ROOT = r"E:\Venom Matches"
STATE = W + r"\prepare-state.json"
LOG = W + r"\prepare-log.txt"
PHASE = globals().get("PM_PHASE", "setup")
DETACHED = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
T0 = time.time()
BUDGET = 42                          # seconds per call (tool limit is 60)
YT_GB_H, TAVO_GB_H = 29.0, 13.5      # 2026-10-26: ~65 Mbps YouTube export (60M preset), 4K H.265 TAVO ~30 Mbps
UTF8 = dict(os.environ, PYTHONIOENCODING="utf-8")


def say(msg, out):
    out.setdefault("log", []).append(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def left():
    return BUDGET - (time.time() - T0)


def rd(path):
    return open(path, encoding="utf-8", errors="replace").read() if os.path.exists(path) else ""


def rm(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ---- Resolve's "Render completed!" pop-up blocks scripting until closed ------
def close_popups():
    user32 = ctypes.windll.user32
    try:
        pids = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process Resolve).Id"],
                              capture_output=True, text=True, timeout=15).stdout.split()
        pids = {int(p) for p in pids}
    except Exception:
        return []
    found = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, lp):
        pid = wt.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd); b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, b, n + 1)
            rc = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(rc))
            w, h = rc.right - rc.left, rc.bottom - rc.top
            title = b.value
            if (title.endswith(".drfx") or "Render" in title) and w < 900 and h < 500:
                found.append((hwnd, title))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    for hwnd, title in found:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    if found:
        time.sleep(1.0)
    return [t for _, t in found]


def run_lua(code, logpath, wait=50):
    rm(logpath)
    resolve.Fusion().Execute(code)   # noqa: F821
    t = time.time()
    while not os.path.exists(logpath) and time.time() - t < wait:
        time.sleep(0.5)
    time.sleep(1.5)
    return rd(logpath) or "NO LOG"


def lua_str(s):
    """a Lua long-bracket string literal (safe for Windows paths and quotes)"""
    return "[==[" + s + "]==]"


def newest_folder():
    """the match folder with the most recently RECORDED camera file (copy-card keeps the
    camera's file times), not the folder touched last — moving old exports out of a
    folder changes that folder's date"""
    def recorded(d):
        ts = [os.path.getmtime(f) for f in glob.glob(d + r"\DJI_*") if re.search(r"\.(mp4|mov)$", f, re.I)]
        return max(ts) if ts else 0
    subs = [d for d in glob.glob(ROOT + r"\*") if os.path.isdir(d)]
    subs = [d for d in subs if recorded(d)]
    return max(subs, key=recorded) if subs else None


def match_json(folder):
    js = glob.glob(folder + r"\*.json")          # copy-info.txt is .txt on purpose
    return max(js, key=os.path.getmtime) if js else None


YT_PRESET_60 = "Venom YouTube 4K60 H265 10-bit 60M"   # 2026-10-26 (Kenny): 60 Mbps target (YouTube's 4K60 guide 53-68); was ~32
YT_PRESET_10 = "Venom YouTube 4K60 H265 10-bit"   # 2026-10-19 (Kenny): 10-bit like the camera (Main10), same encoder settings
YT_PRESET_8 = "Venom YouTube 4K60 H265"          # fallback (8-bit) if the 10-bit preset is missing


def load_youtube_preset(p):
    p.LoadRenderPreset("H.264 Master"); time.sleep(2)
    have = p.GetRenderPresetList() or []
    name = next((n for n in (YT_PRESET_60, YT_PRESET_10) if n in have), YT_PRESET_8)
    p.LoadRenderPreset(name); time.sleep(3)
    return p.GetCurrentRenderFormatAndCodec()


def free_gb(path):
    return shutil.disk_usage(os.path.splitdrive(path)[0] + "\\").free / 1e9


def snapshot_dir(folder):
    d = os.path.join(folder, "_workflow")
    os.makedirs(d, exist_ok=True)
    return d


# =============================================================================
def start_watchdog():
    """Freeze watchdog (2026-10-03): resolve-watch.py writes resolve-watch.txt every
    20 s (OK / FROZEN / GONE). It runs one copy at a time, so starting it from
    every phase is harmless."""
    try:
        subprocess.Popen([PY, W + r"\resolve-watch.py"], creationflags=DETACHED, env=UTF8)
    except Exception:
        pass


def sb_stills():
    """2026-10-19: scoreboard pictures instead of the live Fusion scoreboard (scoreboard-stills.py)"""
    g = {"resolve": resolve, "__name__": "sbs"}   # noqa: F821
    exec(open(W + r"\scoreboard-stills.py", encoding="utf-8").read(), g)
    return g


def setup():
    out = {"phase": "setup"}
    start_watchdog()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("prepare-match " + time.strftime("%Y-%m-%d %H:%M") + "\n")
    close_popups()
    pm = resolve.GetProjectManager()   # noqa: F821
    cur = pm.GetCurrentProject()
    if cur and cur.IsRenderingInProgress():
        say(f"ERROR: '{cur.GetName()}' is still exporting — wait for it to finish (switching projects mid-export can crash Resolve)", out)
        return out
    folder = globals().get("PM_FOLDER") or newest_folder()
    if not folder or not os.path.isdir(folder):
        say(f"ERROR: match folder not found: {folder}", out)
        return out
    js = globals().get("PM_JSON") or match_json(folder)
    if not js:
        say(f"ERROR: no scorekeeper .json in {folder} — get it from Drive first", out)
        return out
    if not [f for f in os.listdir(folder) if re.match(r"DJI_.*\.(mp4|mov)$", f, re.I)]:
        say(f"ERROR: no DJI_ camera files in {folder}", out)
        return out
    m = json.load(open(js, encoding="utf-8"))
    t1, t2, date = m.get("team1", "Venom Rebels"), m.get("team2", "Opponent"), m.get("date", "")
    hhmm = ""
    if m.get("startedAt"):
        hhmm = m["startedAt"][11:13] + m["startedAt"][14:16] + " "
    name = globals().get("PM_PROJECT") or f'{date} {hhmm}{"Venom" if t1 == "Venom Rebels" else t1} vs {t2}'
    say(f"match folder: {folder}", out)
    fm = (m.get("format") or {}).get("code", "bo3 (old file)")
    say(f"match file: {os.path.basename(js)} — {t1} vs {t2}, {len(m.get('events', []))} points, format {fm}", out)
    if name in pm.GetProjectListInCurrentFolder():
        say(f"ERROR: a project called '{name}' already exists — nothing changed (delete/rename it, or set PM_PROJECT)", out)
        return out

    # fresh start for this match: no leftovers from the previous one can be mistaken for this one's
    for f in ("fix-audio-log.txt", "bookends-log.txt", "tavo-log.txt", "bookends.json", "youtube-info.json"):
        rm(W + "\\" + f)
    for f in glob.glob(RDIR + r"\r-*") + glob.glob(RDIR + r"\plan.json") + glob.glob(CAND + r"\*.jpg"):
        rm(f)

    # Never save a fresh "Untitled Project" (right after Resolve starts): that pops
    # up a "Save Current Project" name box that blocks everything.
    if cur and cur.GetName() != "Untitled Project":
        pm.SaveProject()
    p = pm.CreateProject(name)
    if not p:
        close_popups()
        p = pm.CreateProject(name)
    if not p:
        say("ERROR: Resolve refused to create the project", out)
        return out
    resolve.OpenPage("edit")   # noqa: F821
    say(f"project: {name}", out)
    # tournament / event name for the FINAL screen + thumbnail (2026-10-06): PM_EVENT, saved
    # with the match so later re-runs keep it; "" or None keeps an existing event.txt
    ev = (globals().get("PM_EVENT") or "").strip()
    evf = os.path.join(folder, "event.txt")
    if ev:
        open(evf, "w", encoding="utf-8").write(ev)
    ev = rd(evf).strip() if os.path.exists(evf) else ""
    say(f"event: {ev.upper() if ev else '(none - FINAL screen shows the date only' + (', or SCRIMMAGE' if 'scrim' in str(fm) else '') + ')'}", out)

    # 1) footage — THIS folder, passed in (the Lua "newest folder" guess picks by name)
    a = run_lua(f"_G.MATCH_CLIP_FOLDER = {lua_str(folder)}; "
                'dofile("C:/Users/YOURNAME/scoreboard-pipeline/assemble-match.lua"); _G.MATCH_CLIP_FOLDER = nil',
                W + r"\assemble-log.txt")
    fl = re.search(r"Folder:\s*(.+)", a)
    if not fl or os.path.normcase(fl.group(1).strip()) != os.path.normcase(folder):
        say(f"ERROR: assembly used the wrong folder ({fl.group(1).strip() if fl else 'none'}) — stopping", out)
        return out
    keep = [l.strip() for l in a.splitlines() if re.search(r"Camera frame rate|Timeline is|No gaps|MISMATCH|Timeline format|Timeline:|PLAYBACK|\*\*\*|ERROR", l)]
    for l in keep:
        say("assemble: " + l, out)
    if "No gaps" not in a:
        say("ERROR: assembly problem — stopping here", out)
        return out

    # 2) free space: the YouTube export (+ TAVO file when asked for) must fit (before any heavy work)
    # TAVO is OFF by default (2026-10-06, Kenny: the coach picks which games go to TAVO) —
    # PM_TAVO = True turns it on for this match; later: make-tavo.py with TAVO_INFO (see its docstring)
    tavo = bool(globals().get("PM_TAVO"))
    n = re.search(r"Timeline is (\d+) frames", a)
    hours = (int(n.group(1)) / 59.94 / 3600) if n else 1.5
    need = hours * (YT_GB_H + (TAVO_GB_H if tavo else 0)) + 3 + 10
    free = free_gb(folder)
    say(f"space: {free:.0f} GB free, this match needs about {need:.0f} GB", out)
    if free < need:
        say(f"ERROR: not enough space on {os.path.splitdrive(folder)[0]} — move finished matches to the external "
            f"drive first (needs ~{need:.0f} GB, {free:.0f} GB free). Nothing else was started.", out)
        return out

    pl = run_lua('dofile("C:/Users/YOURNAME/scoreboard-pipeline/place-scoreboard.lua")', W + r"\place-log.txt")
    say("place: " + pl.strip().splitlines()[-1], out)
    if "PLACED OK" not in pl:
        say("ERROR: scoreboard clip not placed — use the manual fallback", out)
        return out

    # 3) scoreboard with THIS match file, passed in
    # 2026-10-21: measure the team logos first so build-scoreboard sizes them by their
    # visible drawing (team-logos\_logo-ink.txt); a failure only falls back to the old sizing
    try:
        lz = subprocess.run([PY, W + r"\logo_sizes.py"], capture_output=True, text=True, timeout=60,
                            encoding="utf-8", errors="replace", env=UTF8)
        say((lz.stdout.strip() or lz.stderr.strip() or "logo sizes: no output").splitlines()[-1], out)
    except Exception as e:
        say(f"logo sizes: skipped ({e})", out)
    def lq(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    t = open(OC + r"\_runner_template.lua", encoding="utf-8").read()
    t = (t.replace("PREVIEW_PLACEHOLDER", "nil").replace("MATCHFILE_PLACEHOLDER", lua_str(js))
          .replace("PILLSTYLE_PLACEHOLDER", "nil"))
    t = re.sub(r'_G\.SCOREBOARD_TEAM1 = ".*?"', '_G.SCOREBOARD_TEAM1 = "' + lq(t1) + '"', t)
    t = re.sub(r'_G\.SCOREBOARD_TEAM2 = ".*?"', '_G.SCOREBOARD_TEAM2 = "' + lq(t2) + '"', t)
    t = t.replace('local ok, err = pcall(dofile, "C:/Users/YOURNAME/scoreboard-pipeline/run-overlay.lua")',
                  'local ok, err = pcall(dofile, "C:/Users/YOURNAME/scoreboard-pipeline/run-overlay.lua")\n'
                  '  pcall(dofile, "C:/Users/YOURNAME/scoreboard-pipeline/bake-static.lua")')
    open(OC + r"\_runner_now.lua", "w", encoding="utf-8").write(t)
    rm(W + r"\bake-static-log.txt")
    r = run_lua('dofile("C:/Users/YOURNAME/scoreboard-pipeline/_overlay_check/_runner_now.lua")', OC + r"\run-log.txt")
    closed = close_popups()
    seen = set()
    for l in r.splitlines():
        if re.search(r"Comp:|ERROR|Frame rate:|Set alignment|STILL STATIC|OK$|pop:|Polish:|Point tags|\.\.\.|\*\*\*", l) and l.strip() not in seen:
            seen.add(l.strip())
            say("overlay: " + l.strip(), out)
    b = rd(W + r"\bake-static-log.txt") or "no bake log"
    say("bake: " + b.strip().splitlines()[-1], out)
    if closed:
        say("closed pop-up(s): " + ", ".join(closed), out)
    try:
        yi = json.load(open(W + r"\youtube-info.json", encoding="utf-8"))
        used = yi.get("matchFile", "")
    except Exception:
        used = ""
    if os.path.normcase(used) != os.path.normcase(js):
        say(f"ERROR: the scoreboard used the wrong match file ({used or 'none'}) — stopping", out)
        return out

    # 4) intro / summary plan, then the slow parts in the background
    bp = subprocess.run([PY, W + r"\make-bookends.py", "plan"], capture_output=True, text=True, timeout=90,
                        encoding="utf-8", errors="replace", env=UTF8)
    for l in bp.stdout.strip().splitlines():
        say("bookends: " + l, out)
    fade_end, fade_start = None, 0.0
    if "PLAN OK" in bp.stdout:
        bj = json.load(open(W + r"\bookends.json", encoding="utf-8"))
        fade_end = bj["export_end_frame"] / bj["fps"]
        fade_start = bj.get("trim_s", 0.0)               # front trim (2026-10-01)
        for part in ("intro", "summary"):
            subprocess.Popen([PY, W + r"\make-bookends.py", "render", part], creationflags=DETACHED, env=UTF8)
        say("intro + summary clips drawing in the background (~2-3 min)", out)
    else:
        say("ERROR: bookends plan failed — " + bp.stderr[-300:], out)
    subprocess.Popen([PY, W + r"\fix-audio.py", "make", folder] +
                     ([f"{fade_end:.3f}", f"{fade_start:.3f}"] if fade_end else []),
                     creationflags=DETACHED, env=UTF8)
    if tavo:
        subprocess.Popen([PY, W + r"\make-tavo.py"], creationflags=DETACHED, env=UTF8)
    try:                                                          # set-break wipes, "SET n" (2026-10-06)
        need = sorted(wipe_ids(json.load(open(W + r"\bookends.json", encoding="utf-8")).get("cuts", [])), key=str)
    except Exception:
        need = []
    if need:
        subprocess.Popen([PY, W + r"\make-set-wipe.py"] + [str(n) for n in need], creationflags=DETACHED, env=UTF8)
    subprocess.Popen([PY, W + r"\prep-upload.py", "candidates"], creationflags=DETACHED, env=UTF8)
    say("background: audio fix, thumbnail choices" + (", TAVO video (game play only, 1080p)" if tavo
        else " — TAVO: off (not asked for; can be made later for this match)"), out)

    pm.SaveProject()
    json.dump({"project": name, "folder": folder, "json": js, "team1": t1, "team2": t2, "date": date,
               "render_tries": 0, "tavo": tavo}, open(STATE, "w", encoding="utf-8"))
    out["ok"] = ("LUA ERROR" not in r) and ("BAKED OK" in b) and ("PLAN OK" in bp.stdout)
    say("SETUP DONE — run finish in ~3 min" if out["ok"] else "*** SETUP FINISHED WITH PROBLEMS — read the lines above ***", out)
    return out


def cut_words(bj):
    """'set breaks removed: 4, time-outs removed: 2' (2026-10-19)"""
    cs = bj.get("cuts", [])
    nt = sum(1 for c in cs if c.get("kind") == "timeout")
    nc = sum(1 for c in cs if c.get("kind") == "camera")
    w = f"set breaks removed: {len(cs) - nt - nc}" + (f", camera-gap wipes: {nc}" if nc else "")
    return w + (f", time-outs removed: {nt}" if nt else "")


def wipe_ids(cuts):
    """2026-10-19: set numbers for set-break wipes, 'timeout' for the TIME-OUT wipe"""
    return {"timeout" if c.get("kind") == "timeout" else (c.get("wipe") or "camera") if c.get("kind") == "camera" else c["next_set"] for c in cuts}


def wipes_ready():
    """every 'SET n' / 'TIME-OUT' wipe this match's cuts need exists (2026-10-06; time-outs 2026-10-19)"""
    try:
        need = wipe_ids(json.load(open(W + r"\bookends.json", encoding="utf-8")).get("cuts", []))
        if not need:
            return True
        sw = json.load(open(W + r"\set-wipe\set-wipe.json", encoding="utf-8"))
        have = set(sw.get("sets", [])) | set(sw.get("labels", []))
        return need <= have and "WIPE READY" in rd(W + r"\set-wipe\set-wipe-log.txt")
    except Exception:
        return False


# =============================================================================
def finish():
    out = {"phase": "finish"}
    start_watchdog()
    st = json.load(open(STATE, encoding="utf-8"))
    close_popups()
    pm = resolve.GetProjectManager()   # noqa: F821
    p = pm.GetCurrentProject()
    if p.GetName() != st["project"]:
        say(f"ERROR: current project is {p.GetName()}, expected {st['project']}", out)
        return out
    folder = st["folder"]
    # 2026-10-19: a re-run after an export starts from the normal timeline (no scoreboard pictures)
    try:
        _tl = next((x for x in (p.GetTimelineByIndex(i) for i in range(1, p.GetTimelineCount() + 1))
                    if x.GetName().startswith("Match ")), None)
        _done = sb_stills()["restore"](p, _tl) if _tl else []
        if _done:
            say("scoreboard pictures taken off first: " + "; ".join(_done), out)
    except Exception as e:
        say(f"ERROR: couldn't take the scoreboard pictures off ({e}) — run PM_PHASE='sb_restore'", out)
        return out

    def wait(msg):
        say("waiting: " + msg + " — run finish again", out)
        out["waiting"] = True
        return out

    # --- 1. background work ready? ---------------------------------------------
    fa, bl = rd(W + r"\fix-audio-log.txt"), rd(W + r"\bookends-log.txt")
    if "FAILED" in bl:
        say("ERROR: drawing the intro/summary failed — see bookends-log.txt", out)
        return out
    if "ERROR" in fa or "MISMATCH" in fa:
        say("ERROR: the audio fix failed — see fix-audio-log.txt", out)
        return out
    tl = p.GetCurrentTimeline()
    a1 = tl.GetItemListInTrack("audio", 1) or []
    swapped = len(a1) == 1 and a1[0].GetName() == "match-audio-normalized.wav"
    pending = [x for x, ok in (("audio", swapped or "AUDIO READY" in fa),
                               ("intro", "INTRO READY" in bl or "INTRO SKIPPED" in bl),
                               ("summary", "SUMMARY READY" in bl),
                               ("set-break wipe", wipes_ready())) if not ok]
    if pending:
        return wait("not ready yet: " + ", ".join(pending))

    # --- 2. audio + bookends into the timeline (once) ---------------------------
    if not swapped:
        resolve.OpenPage("edit")   # noqa: F821
        exec(open(W + r"\fix-audio.py", encoding="utf-8").read(), {"resolve": resolve, "__name__": "resolve_swap"})  # noqa: F821
        pm.SaveProject()
        for l in rd(W + r"\fix-audio-log.txt").splitlines():
            if re.search(r"Check|WAV:|SWAPPED|PROBLEM|ERROR", l):
                say("audio: " + l.strip(), out)
    bj = json.load(open(W + r"\bookends.json", encoding="utf-8"))
    if "export_out" not in bj:
        resolve.OpenPage("edit")   # noqa: F821
        n0 = len(rd(W + r"\bookends-log.txt"))
        exec(open(W + r"\place-bookends.py", encoding="utf-8").read(), {"resolve": resolve, "__name__": "place_bookends"})  # noqa: F821
        pm.SaveProject()      # 2026-10-03: save after each big step (a freeze loses nothing)
        for l in rd(W + r"\bookends-log.txt")[n0:].splitlines():
            say("bookends: " + l[9:], out)
        bj = json.load(open(W + r"\bookends.json", encoding="utf-8"))
        for fl in bj.get("flags", []):
            say("FLAG: " + fl, out)
    if not ("export_out" in bj and "BOOKENDS PLACED OK" in rd(W + r"\bookends-log.txt")):
        say("ERROR: intro/summary placement problem — see bookends-log.txt", out)
        return out
    out["flags"] = bj.get("flags", [])
    out["export_in"], out["export_out"] = bj.get("export_in"), bj.get("export_out")

    # --- 3. review-sheet frames: only the missing ones, never restarted ----------
    if not os.path.exists(RDIR + r"\plan.json"):
        subprocess.run([PY, W + r"\make-review-sheet.py", "plan"], capture_output=True, text=True, timeout=30, env=UTF8)
    plan = json.load(open(RDIR + r"\plan.json", encoding="utf-8"))
    def missing():
        return [row for row in plan if not (os.path.exists(RDIR + f'\\r-{row["frame"]}.mp4')
                                            and os.path.getsize(RDIR + f'\\r-{row["frame"]}.mp4') > 0)]
    if p.IsRenderingInProgress():
        while p.IsRenderingInProgress() and left() > 8:
            time.sleep(0.5)
        if p.IsRenderingInProgress():
            return wait(f"review pictures still rendering ({len(missing())} of {len(plan)} to go)")
    todo = missing()
    if todo:
        st["render_tries"] = st.get("render_tries", 0) + 1
        json.dump(st, open(STATE, "w", encoding="utf-8"))
        if st["render_tries"] > 4:
            say(f"ERROR: {len(todo)} review pictures won't render — check the Deliver page", out)
            return out
        resolve.OpenPage("deliver")   # noqa: F821
        p.DeleteAllRenderJobs()
        fc = load_youtube_preset(p)
        if fc.get("codec") != "H265_NVIDIA":
            fc = load_youtube_preset(p)
        st0 = tl.GetStartFrame()
        for row in todo:
            p.SetRenderSettings({"SelectAllFrames": False, "MarkIn": st0 + row["frame"], "MarkOut": st0 + row["frame"],
                                 "TargetDir": RDIR, "CustomName": f'r-{row["frame"]}'})
            p.AddRenderJob()
        p.StartRendering()
        time.sleep(1)
        while p.IsRenderingInProgress() and left() > 8:
            time.sleep(0.5)
        if p.IsRenderingInProgress():
            return wait(f"review pictures rendering ({len(todo)} queued)")
    close_popups()
    p.DeleteAllRenderJobs()
    if missing():
        return wait(f"{len(missing())} review pictures didn't come out — rendering them again")

    # --- 4. sheet, YouTube text, thumbnail choices, TAVO ---------------------------
    rs = subprocess.run([PY, W + r"\make-review-sheet.py", "sheet"], capture_output=True, text=True, timeout=60, env=UTF8)
    sheet = rs.stdout.strip().splitlines()[-1] if rs.stdout.strip() else rs.stderr[-300:]
    say(f"review sheet: {sheet}", out)
    out["sheet"] = sheet.split(" (")[0]
    rt = subprocess.run([PY, W + r"\prep-upload.py", "text"], capture_output=True, text=True, timeout=60, env=UTF8)
    txt = [l for l in rt.stdout.splitlines() if l.endswith("YouTube text.txt")]
    out["youtube_text"] = txt[0] if txt else None
    say("YouTube text: " + (txt[0] if txt else "FAILED " + rt.stderr[-200:]), out)
    contact = CAND + r"\contact.jpg"
    if not os.path.exists(contact):
        if not glob.glob(CAND + r"\cand-*.jpg"):
            subprocess.Popen([PY, W + r"\prep-upload.py", "candidates"], creationflags=DETACHED, env=UTF8)
        return wait("thumbnail choices still being made")
    out["thumb_contact"] = contact
    say("thumbnail choices: " + contact, out)
    if not st.get("tavo"):
        out["tavo"] = "off"
        say("TAVO: off (not asked for this match)", out)
    else:
        tv = rd(W + r"\tavo-log.txt")
        for l in tv.splitlines():
            if l[9:].startswith(("keeping", "TAVO", "***")) or " GB, " in l:
                say("TAVO: " + l[9:], out)
        out["tavo"] = "ready" if "TAVO READY" in tv else ("FAILED" if "FAILED" in tv else "encoding")
        if out["tavo"] == "encoding":
            say("TAVO: still encoding in the background — it finishes on its own", out)

    # --- 5. per-match snapshot (another match can be set up while this one exports)
    snap = snapshot_dir(folder)
    for f in ("bookends.json", "youtube-info.json", "prepare-state.json"):
        shutil.copy2(W + "\\" + f, os.path.join(snap, f))
    shutil.copy2(RDIR + r"\plan.json", os.path.join(snap, "review-plan.json"))
    resolve.OpenPage("edit")   # noqa: F821
    pm.SaveProject()
    out["ok"] = (" 0 missing" in sheet) and bool(out.get("youtube_text"))
    say("FINISH DONE — pick the thumbnail (prep-upload.py thumbnail <n>), then show Kenny the sheet + thumbnail + text"
        if out["ok"] else "*** FINISH HAD PROBLEMS ***", out)
    return out


# =============================================================================
def current_match():
    """(project, folder, snapshot dict) for the project that's open in Resolve"""
    p = resolve.GetProjectManager().GetCurrentProject()   # noqa: F821
    tl = None
    for i in range(1, p.GetTimelineCount() + 1):
        x = p.GetTimelineByIndex(i)
        if x.GetName().startswith("Match "):
            tl = x
    v1 = tl.GetItemListInTrack("video", 1) if tl else []
    folder = os.path.dirname(v1[0].GetMediaPoolItem().GetClipProperty("File Path")) if v1 else ""
    snap = os.path.join(folder, "_workflow")
    s = {}
    for f in ("bookends.json", "prepare-state.json", "youtube-info.json"):
        try:
            s[f] = json.load(open(os.path.join(snap, f), encoding="utf-8"))
        except Exception:
            pass
    return p, tl, folder, s


def export():
    out = {"phase": "export"}
    start_watchdog()
    p, tl, folder, s = current_match()
    if "bookends.json" not in s or "prepare-state.json" not in s:
        say(f"ERROR: no finished preparation for '{p.GetName()}' ({folder}\\_workflow missing) — run setup + finish first", out)
        return out
    bj, st = s["bookends.json"], s["prepare-state.json"]
    if st["project"] != p.GetName():
        say(f"ERROR: the open project is '{p.GetName()}' but {folder} belongs to '{st['project']}'", out)
        return out
    if p.IsRenderingInProgress() and not sb_stills()["building"](p, folder):   # (2026-10-19: or drawing the scoreboard pictures)
        say("already exporting — use export_status", out)
        return out
    tv = rd(W + r"\tavo-log.txt")
    if (folder.lower() in tv.lower() and "TAVO READY" not in tv and "FAILED" not in tv
            and not globals().get("PM_FORCE")):
        say("waiting: the TAVO file is still encoding (both use the graphics card) — try again in a few minutes", out)
        out["waiting"] = True
        return out
    frames = bj["export_out"] - bj["export_in"] + 1
    # set-break cuts (2026-10-06): each kept stretch of the Match timeline is exported as
    # its own part and join-parts.py joins them (a nested cut timeline exported ~40 % slower)
    ranges = []
    if bj.get("cuts"):
        pos = bj["export_in"]
        for c in bj["cuts"]:
            ranges.append((pos, tl.GetStartFrame() + c["out_frame"] - 1)); pos = tl.GetStartFrame() + c["in_frame"]
        ranges.append((pos, bj["export_out"]))
        frames = sum(b - a + 1 for a, b in ranges)
    need = frames / bj["fps"] / 3600 * YT_GB_H + 3
    free = free_gb(folder)
    if free < need:
        say(f"ERROR: not enough space for the export ({free:.0f} GB free, needs ~{need:.0f} GB)", out)
        return out
    info = s.get("youtube-info.json") or {}
    name = globals().get("PM_EXPORT_NAME") or f'{info.get("date", st["date"])} {st["team1"]} vs {st["team2"]} - YouTube'
    # never overwrite an existing export (2026-09-28 — a test once overwrote a finished file)
    if os.path.exists(os.path.join(folder, name + ".mp4")):
        say(f"ERROR: {name}.mp4 already exists in {folder} — nothing started. Move/rename it first "
            "(Kenny decides), or use PM_EXPORT_NAME for a different name.", out)
        return out
    # 2026-10-19 (Kenny "go"): scoreboard pictures instead of the live Fusion scoreboard —
    # ~2.4x faster export, no slowdown (scoreboard-stills.py). Anything odd -> live scoreboard.
    sb_used, sbs = False, None
    if not globals().get("PM_LIVE_SCOREBOARD"):
        sbs = sb_stills()
        if sbs["mode"]() == "stills":
            close_popups()
            r_ = sbs["step"](p, tl, folder, T0 + BUDGET)
            if r_["state"] == "waiting":           # progress: not written to prepare-log (too chatty)
                out.setdefault("log", []).append(r_["msg"])
                out.update({"waiting": True, "retry_s": r_.get("retry_s", 10)})
                return out
            if r_["state"] == "error":
                say("ERROR: " + r_["msg"], out)
                return out
            say(r_["msg"], out)
            sb_used = r_["state"] == "ready"
            if not sb_used:
                sbs["consume"](p, folder, False)
        else:
            say("scoreboard: live (scoreboard-mode.txt says live)", out)
    else:
        say("scoreboard: live (asked for this run)", out)
    close_popups()
    # 2026-10-19 (Kenny "go"): with the scoreboard pictures the nested "YouTube cut" timeline exports
    # as fast as the parts (zz test: 106.6 vs 106 fps; the ~40 % penalty was the live Fusion
    # scoreboard), so it goes out as ONE file — no join afterwards (~3-4 min saved on a full match,
    # audio encoded once). Live scoreboard: parts + join as before.
    single = None
    if ranges and sb_used and bj.get("cut_timeline"):
        single = next((x for x in (p.GetTimelineByIndex(i) for i in range(1, p.GetTimelineCount() + 1))
                       if x.GetName() == bj["cut_timeline"]), None)
        if single and single.GetEndFrame() - single.GetStartFrame() != frames:
            say(f"(YouTube cut timeline is {single.GetEndFrame() - single.GetStartFrame()} frames, "
                f"expected {frames} — exporting parts instead)", out)
            single = None
    resolve.OpenPage("deliver")   # noqa: F821
    p.DeleteAllRenderJobs()
    if single:
        p.SetCurrentTimeline(single)
    fc = load_youtube_preset(p)
    if fc.get("codec") != "H265_NVIDIA":
        fc = load_youtube_preset(p)
    if fc.get("codec") != "H265_NVIDIA":
        say(f"ERROR: the YouTube preset didn't load (got {fc})", out)
        return out
    if not single and p.GetCurrentTimeline().GetName() != tl.GetName():
        p.SetCurrentTimeline(tl)
    jobs, parts = [], []
    if single:
        p.SetRenderSettings({"SelectAllFrames": True, "TargetDir": folder, "CustomName": name})
        job = p.AddRenderJob(); jobs = [job]
    elif ranges:
        pdir = os.path.join(folder, "_workflow", "parts " + time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(pdir)
        for k, (a, b) in enumerate(ranges, 1):
            p.SetRenderSettings({"SelectAllFrames": False, "MarkIn": a, "MarkOut": b,
                                 "TargetDir": pdir, "CustomName": f"part {k}"})
            jobs.append(p.AddRenderJob()); parts.append(os.path.join(pdir, f"part {k}.mp4"))
        json.dump({"parts": parts, "out": os.path.join(folder, name + ".mp4"), "frames": frames},
                  open(os.path.join(pdir, "parts.json"), "w", encoding="utf-8"), indent=1)
        job = jobs[0]
    else:
        p.SetRenderSettings({"SelectAllFrames": False, "MarkIn": bj["export_in"], "MarkOut": bj["export_out"],
                             "TargetDir": folder, "CustomName": name})
        job = p.AddRenderJob(); jobs = [job]
    p.StartRendering()
    if sb_used:
        sbs["consume"](p, folder, True)
    # 2026-10-14: passive export monitor (file growth, GPU, CPU, other busy programs once a
    # minute -> _workflow\export-monitor-summary.txt). Never talks to Resolve; a failure here
    # never affects the export.
    try:
        subprocess.Popen([PY, W + r"\export-monitor.py", pdir if (ranges and not single) else folder,
                          os.path.join(folder, name + ".mp4")], creationflags=DETACHED, env=UTF8)
    except Exception:
        pass
    st.update({"scoreboard": "pictures" if sb_used else "live"})
    out["scoreboard"] = "pictures" if sb_used else "live"
    st.update({"export_job": job, "export_jobs": jobs, "export_parts": parts,
               "export_file": os.path.join(folder, name + ".mp4"), "export_frames": frames,
               "export_started": time.strftime("%Y-%m-%d %H:%M:%S")})
    json.dump(st, open(os.path.join(folder, "_workflow", "prepare-state.json"), "w", encoding="utf-8"))
    mins = frames / bj["fps"] / 60
    # 2026-10-03 speed tests: ~1.1x the video length with live logos, ~0.8x
    # once the logos are pre-drawn (30 s -> 23.3 s; plain decode+encode floor is
    # ~0.78x). 0.95x leaves a margin. The 2026-10-01 export took 1.6x only because
    # the preset was also uploading to YouTube inside the render job (now off).
    # 2026-10-19: with the scoreboard pictures last night's match rendered at ~114 fps (0.53x); 0.6x margin
    fac = 0.6 if sb_used else 0.95
    eta = time.time() + mins * fac * 60
    eta_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(eta)) + \
        time.strftime("%z", time.localtime(eta))[:3] + ":" + time.strftime("%z", time.localtime(eta))[3:]
    if single:
        say(f"{cut_words(bj)} ({bj.get('cut_total_s', 0) / 60:.1f} min) — "
            f"exporting the YouTube cut timeline as one file (no join needed)", out)
    elif ranges:
        say(f"{cut_words(bj)} ({bj.get('cut_total_s', 0) / 60:.1f} min) — "
            f"exporting {len(ranges)} parts, joined automatically afterwards (export_status)", out)
    say(f"EXPORT STARTED: {name}.mp4 — {frames} frames ({mins:.0f} min of video), "
        f"about {mins * fac:.0f} min to render (done ~{time.strftime('%H:%M', time.localtime(eta))}); "
        f"{free:.0f} GB free", out)
    out.update({"ok": True, "file": st["export_file"], "frames": frames,
                "eta": time.strftime("%H:%M", time.localtime(eta)), "eta_iso": eta_iso})
    return out


def export_status():
    out = {"phase": "export_status"}
    p, tl, folder, s = current_match()
    st = s.get("prepare-state.json") or {}
    if p.IsRenderingInProgress():
        pct = None
        try:
            js = st.get("export_jobs") or [st.get("export_job")]
            pct = round(sum(p.GetRenderJobStatus(j).get("CompletionPercentage", 0) for j in js) / len(js))
        except Exception:
            pass
        out.update({"rendering": True, "percent": pct})
        # measured finish time (2026-10-08): from the real render speed so far, +2 min margin
        # (+3 min more when set-break parts still have to be joined afterwards)
        try:
            t0 = time.mktime(time.strptime(st["export_started"], "%Y-%m-%d %H:%M:%S"))
            if pct and pct >= 3:
                eta = t0 + (time.time() - t0) * 100 / pct + 120 + (180 if st.get("export_parts") else 0)
                z = time.strftime("%z", time.localtime(eta))
                out.update({"eta": time.strftime("%H:%M", time.localtime(eta)),
                            "eta_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(eta)) + z[:3] + ":" + z[3:]})
        except Exception:
            pass
        say(f"exporting: {pct if pct is not None else '?'}%" + (f", done ~{out['eta']} (measured)" if out.get("eta") else ""), out)
        return out
    close_popups()
    f = st.get("export_file", "")
    if st.get("export_parts") and not os.path.exists(f):     # set-break cuts: join the parts (2026-10-06)
        pdir = os.path.dirname(st["export_parts"][0])
        jl = rd(os.path.join(pdir, "join-parts-log.txt"))
        if "JOIN FAILED" in jl:
            say("ERROR: joining the parts failed — " + jl.strip().splitlines()[-1][9:], out)
            return out
        if not jl:
            missing = [x for x in st["export_parts"] if not os.path.exists(x)]
            if missing:
                say(f"ERROR: export part(s) missing: {', '.join(os.path.basename(x) for x in missing)} — export again", out)
                return out
            subprocess.Popen([PY, W + r"\join-parts.py", os.path.join(pdir, "parts.json")], creationflags=DETACHED, env=UTF8)
        say("joining the parts into one video (~1-3 min) — check again shortly", out)
        out.update({"rendering": True, "joining": True})
        return out
        say(f"ERROR: export file not found: {f}", out)
        return out
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                    "stream=codec_type,codec_name,width,height,nb_frames,r_frame_rate",
                                    "-of", "json", f], capture_output=True, text=True).stdout or "{}")
    v = [x for x in pr.get("streams", []) if x.get("codec_type") == "video"]
    a = [x for x in pr.get("streams", []) if x.get("codec_type") == "audio"]
    ok = (bool(v) and v[0].get("codec_name") == "hevc" and v[0].get("width") == 3840
          and v[0].get("r_frame_rate") == "60000/1001" and int(v[0].get("nb_frames", 0)) == st.get("export_frames")
          and bool(a) and a[0].get("codec_name") == "aac")
    gb = os.path.getsize(f) / 1e9 if os.path.exists(f) else 0
    # 2026-10-19: scoreboard pictures off again, live scoreboard back on (the timeline as before)
    try:
        _done = sb_stills()["restore"](p, tl) if tl else []
        if _done:
            resolve.GetProjectManager().SaveProject()   # noqa: F821
            say("scoreboard pictures taken off again: " + "; ".join(_done), out)
    except Exception as e:
        say(f"WARNING: couldn't take the scoreboard pictures off ({e}) — run PM_PHASE='sb_restore'", out)
    say(("EXPORT OK: " if ok else "*** EXPORT CHECK FAILED: ") +
        f"{os.path.basename(f)} — {v[0].get('nb_frames') if v else '?'} frames (expected {st.get('export_frames')}), "
        f"{v[0].get('codec_name') if v else '?'} {v[0].get('width') if v else '?'}x{v[0].get('height') if v else '?'}, "
        f"audio {a[0].get('codec_name') if a else 'none'}, {gb:.1f} GB", out)
    p.DeleteAllRenderJobs()
    if tl and p.GetCurrentTimeline().GetName() != tl.GetName():
        p.SetCurrentTimeline(tl)             # back from the "YouTube cut" timeline
    resolve.OpenPage("edit")   # noqa: F821
    out.update({"ok": ok, "file": f, "done": True})
    return out


def sb_prepare():
    """2026-10-19 (Kenny "go"): draw the scoreboard pictures ahead of the export — run-match calls
    this while it waits for the picture choice (which only changes the camera clips)."""
    out = {"phase": "sb_prepare"}
    p, tl, folder, s = current_match()
    if globals().get("PM_LIVE_SCOREBOARD"):
        out["state"] = "live"; return out
    sbs = sb_stills()
    if sbs["mode"]() != "stills":
        out["state"] = "live"; return out
    if p.IsRenderingInProgress() and not sbs["building"](p, folder):
        out.update({"state": "busy", "retry_s": 30}); return out
    close_popups()
    r_ = sbs["step"](p, tl, folder, T0 + BUDGET)
    out.update(r_)
    out.setdefault("log", []).append(r_["msg"])
    if r_["state"] != "waiting":
        say(r_["msg"] + " (drawn ahead of the export)", out)
    return out


def sb_restore():
    out = {"phase": "sb_restore"}
    p, tl, folder, s = current_match()
    if p.IsRenderingInProgress():
        say("exporting right now — stop the export first", out)
        return out
    done = sb_stills()["restore"](p, tl)
    resolve.GetProjectManager().SaveProject()   # noqa: F821
    say("scoreboard pictures: " + ("; ".join(done) if done else "nothing to undo"), out)
    out["ok"] = True
    return out


result = {"setup": setup, "finish": finish, "export": export, "export_status": export_status,
          "sb_restore": sb_restore, "sb_prepare": sb_prepare}.get(
    PHASE, lambda: {"error": f"unknown PM_PHASE {PHASE}"})()
