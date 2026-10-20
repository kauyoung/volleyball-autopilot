"""
Venom Rebels — one-command end-to-end test on the permanent fixture (2026-10-14).

    python zz-test.py                      # one zz match through run-match.py, export included
    python zz-test.py --tournament         # two zz matches through run-tournament.py --test
    python zz-test.py -- --offset 6        # anything after "--" goes to run-match.py
    python zz-test.py --no-export          # stop after setup/finish (run-match --hold-export; single match)
    python zz-test.py --keep-state         # don't put the real status/summary files back
    python zz-test.py --timeout 152        # 2026-10-19: add a time-out tap at 152 s to the zz copy's match file
                                           # (later points moved 30 s; min cut 8 s, fallback 15 s for the short fixture)

Safety (Kenny, 2026-10-14 — two earlier tests overwrote real files):
  * refuses to start while a real run is busy or Resolve is rendering;
  * snapshots every state file in the scripts folder (status/summary/result/log .txt/.json,
    approval kits) and PUTS THEM BACK afterwards; the test's own copies go to
    _overlay_check\\zz-test-out\\<time>\\state\\;
  * works only in fresh "E:\\Venom Matches\\zz test <time>" folders made from
    _zz-fixture-master (clip hard-linked, no extra space); older zz test folders are removed;
  * lists every real match folder + the Drive scorekeeper folder before and after and
    FAILS the test if anything there changed.
Status: zz-test-status.txt (last line ZZ TEST PASSED / ZZ TEST FAILED: …). Report:
_overlay_check\\zz-test-out\\<time>\\report.txt. Run it detached (it takes ~10-20 min).
"""
import glob, json, os, shutil, subprocess, sys, time, traceback

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
PY = r"C:\Python314\python.exe"
OC = W + r"\_overlay_check"
ROOT = r"E:\Venom Matches"
MASTER = os.path.join(ROOT, "_zz-fixture-master")
DRIVE_DIR = "F:\\My Drive\\Venom Matches \u2013 Scorekeeper"
STATUS = W + r"\zz-test-status.txt"
TS = time.strftime("%Y%m%d-%H%M%S")
OUT = OC + r"\zz-test-out" + "\\" + TS
BACKUP = OC + r"\zz-state-backup" + "\\" + TS
NOWIN = 0x08000000
STATE_EXT = (".txt", ".json", ".pid")
STATE_DIRS = (r"_overlay_check\approval", r"_overlay_check\approval-small", r"_overlay_check\tournament",
              r"_overlay_check\thumb-candidates")
STATE_FILES = (r"_overlay_check\picture-check.jpg",)
FINAL = ("RUN STOPPED", "EXPORT OK", "TOURNAMENT EXPORTS DONE", "TOURNAMENT STOPPED", "ZZ TEST")
report = []


def st(msg, first=False):
    with open(STATUS, "w" if first else "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    report.append(msg)


def is_zz(name):
    return name.lower().startswith(("zz", "_zz"))


def listing(top, real_only=True):
    """{relative path: (size, mtime)} for every file, skipping zz folders."""
    out = {}
    if not os.path.isdir(top):
        return out
    for base, dirs, files in os.walk(top):
        if real_only:
            dirs[:] = [d for d in dirs if not is_zz(d)]
        for f in files:
            p = os.path.join(base, f)
            try:
                s = os.stat(p); out[os.path.relpath(p, top)] = (s.st_size, round(s.st_mtime))
            except OSError:
                pass
    return out


def busy():
    """Reason a real run is in progress, or None."""
    for f in ("run-match-status.txt", "tournament-status.txt"):
        p = os.path.join(W, f)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 600:
            tail = (open(p, encoding="utf-8", errors="replace").read().strip().splitlines() or [""])[-1]
            if not any(k in tail for k in FINAL):
                return f"{f} changed in the last 10 min ({tail[9:80]})"
    try:
        sys.path.append(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
        os.environ.setdefault("RESOLVE_SCRIPT_LIB", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
        import DaVinciResolveScript as d
        r = d.scriptapp("Resolve")
        if not r:
            return "Resolve isn't open (Kenny opens it from the Start menu)"
        p = r.GetProjectManager().GetCurrentProject()
        if p and p.IsRenderingInProgress():
            return f"Resolve is rendering ({p.GetName()})"
    except Exception as e:
        return "can't reach Resolve: " + repr(e)[:100]
    return None


def snapshot():
    os.makedirs(BACKUP, exist_ok=True)
    saved = []
    for f in os.listdir(W):
        p = os.path.join(W, f)
        if os.path.isfile(p) and f.lower().endswith(STATE_EXT) and f != "zz-test-status.txt":
            shutil.copy2(p, BACKUP); saved.append(f)
    for rel in STATE_FILES:
        p = os.path.join(W, rel)
        if os.path.exists(p):
            os.makedirs(os.path.dirname(os.path.join(BACKUP, rel)), exist_ok=True)
            shutil.copy2(p, os.path.join(BACKUP, rel)); saved.append(rel)
    for rel in STATE_DIRS:
        p = os.path.join(W, rel)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(BACKUP, rel)); saved.append(rel + "\\")
    with open(os.path.join(BACKUP, "_saved.json"), "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=1)
    return saved


def restore(saved):
    """Test's own state -> OUT\\state; real state back from BACKUP."""
    keep = os.path.join(OUT, "state")
    os.makedirs(keep, exist_ok=True)
    for f in os.listdir(W):
        p = os.path.join(W, f)
        if os.path.isfile(p) and f.lower().endswith(STATE_EXT) and f != "zz-test-status.txt" \
                and os.path.getmtime(p) >= T0 - 2:
            shutil.copy2(p, keep)
            if f not in saved:
                os.replace(p, os.path.join(keep, "_moved-" + f))   # made by the test: moved out
    for rel in STATE_DIRS:
        p = os.path.join(W, rel)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(keep, rel.replace("\\", "_")), dirs_exist_ok=True)
            shutil.rmtree(p, ignore_errors=True)
    for rel in saved:
        src = os.path.join(BACKUP, rel.rstrip("\\"))
        dst = os.path.join(W, rel.rstrip("\\"))
        if rel.endswith("\\"):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def add_timeout(folder, t):
    """2026-10-19: time-out tap in the zz copy's match file only (never the master)"""
    for js in glob.glob(os.path.join(folder, "*.json")):
        j = json.load(open(js, encoding="utf-8"))
        if "events" not in j:
            continue
        st = max([e["set"] for e in j["events"] if e["t"] <= t] or [1])
        j["timeouts"] = [{"t": float(t), "set": st}]
        # the fixture's points are 6-8 s apart: make room for a time-out (later points +30 s)
        for e in j["events"]:
            if e["t"] > t:
                e["t"] = round(e["t"] + 30.0, 3)
        json.dump(j, open(js, "w", encoding="utf-8"), indent=1)
        return f"time-out tap at {t} s (set {st}) added to {os.path.basename(js)}"
    return "no match file to add the time-out to"


def tidy_after():
    """2026-10-19 (Kenny): the test cleans up after itself — its Resolve test project(s) are deleted
    (zz test / zz tournament only, never while rendering) and only the last 3 test logs and
    state backups are kept. Returns a short note."""
    notes = []
    try:
        import DaVinciResolveScript as d
        pm = d.scriptapp("Resolve").GetProjectManager()
        cur = pm.GetCurrentProject()
        is_zz = lambda n: n.lower().startswith(("zz test 2", "zz tournament"))
        if cur and cur.IsRenderingInProgress():
            notes.append("test project(s) kept (Resolve is rendering)")
        else:
            if cur and is_zz(cur.GetName()):
                cur.DeleteAllRenderJobs()
                pm.CloseProject(cur)
            gone = [n for n in (pm.GetProjectListInCurrentFolder() or []) if is_zz(n) and pm.DeleteProject(n)]
            notes.append(f"{len(gone)} test project(s) removed from Resolve")
    except Exception as e:
        notes.append(f"test projects not removed ({e!r:.80})")
    for top in (OC + r"\zz-test-out", OC + r"\zz-state-backup"):
        old = sorted(d_ for d_ in glob.glob(top + r"\2*") if os.path.isdir(d_))[:-3]
        for d_ in old:
            shutil.rmtree(d_, ignore_errors=True)
        if old:
            notes.append(f"{len(old)} old folder(s) removed from {os.path.basename(top)}")
    return "tidy: " + "; ".join(notes)


def make_folder(tag):
    f = os.path.join(ROOT, f"zz test {TS}{tag}")
    os.makedirs(f)
    for src in glob.glob(MASTER + r"\*"):
        dst = os.path.join(f, os.path.basename(src))
        if src.upper().endswith(".MP4"):
            os.link(src, dst)                     # same drive: no extra space, never touches the master
        else:
            shutil.copy2(src, dst)
    return f


def old_test_folders():
    for d in glob.glob(os.path.join(ROOT, "zz test 2*")):
        if os.path.basename(d).lower().startswith("zz test 2"):
            shutil.rmtree(d, ignore_errors=True)
            if os.path.exists(d):
                report.append("note: couldn't remove old test folder (in use?) " + d)


def wait_export(project, folder):
    """Poll prepare-match export_status for the zz project until EXPORT OK (max 40 min)."""
    sys.path.insert(0, W)
    import DaVinciResolveScript as d
    r = d.scriptapp("Resolve")
    src = open(W + r"\prepare-match.py", encoding="utf-8").read()
    for i in range(80):
        g = {"resolve": r, "PM_PHASE": "export_status", "PM_PROJECT": project, "PM_FOLDER": folder, "__name__": "pm"}
        try:
            exec(src, g)
        except SystemExit:
            pass
        res = g.get("result") or {}
        lg = res.get("log") or [""]
        if res.get("done") or any("EXPORT OK" in l for l in lg):
            return "EXPORT OK — " + lg[-1][:150]
        if any("ERROR" in l for l in lg):
            return "EXPORT FAILED — " + lg[-1][:150]
        time.sleep(30)
    return "EXPORT FAILED — not done after 40 min"


def check_pictures(project):
    """2026-10-19: the export must have used the scoreboard pictures (unless scoreboard-mode.txt
    says live), and after export_status the Match timeline must be back to normal."""
    try:
        if open(W + r"\scoreboard-mode.txt", encoding="utf-8").read().strip().lower().startswith("live"):
            return "scoreboard pictures: switched off (scoreboard-mode.txt) — not checked"
    except Exception:
        pass
    try:
        s = json.load(open(os.path.join(r"E:\Scoreboard stills", project, "state.json"), encoding="utf-8"))
    except Exception as e:
        return f"SCOREBOARD PICTURES NOT USED: no build found ({e})"
    if not s.get("used"):
        return "SCOREBOARD PICTURES NOT USED: " + str(s.get("reason") or s.get("stage"))
    import DaVinciResolveScript as d
    p = d.scriptapp("Resolve").GetProjectManager().GetCurrentProject()
    tl = next((p.GetTimelineByIndex(i) for i in range(1, p.GetTimelineCount() + 1)
               if p.GetTimelineByIndex(i).GetName().startswith("Match ")), None)
    names = [tl.GetTrackName("video", k) for k in range(1, tl.GetTrackCount("video") + 1)] if tl else []
    sb = [it for k in range(1, len(names) + 1) for it in (tl.GetItemListInTrack("video", k) or []) if it.GetName() == "Scoreboard"]
    if "Scoreboard stills" in names or not sb or not all(it.GetClipEnabled() for it in sb):
        return f"SCOREBOARD PICTURES NOT TAKEN OFF after the export (tracks {names})"
    return (f"scoreboard pictures OK: {s.get('files')} files drawn in {s.get('render_s')} s, {s.get('items')} pieces, "
            f"whole-frame check {s.get('comp_result')}, timeline back to normal")


def main():
    args = sys.argv[1:]
    passthru = args[args.index("--") + 1:] if "--" in args else []
    args = args[:args.index("--")] if "--" in args else args
    tourn, keep_state, no_export = "--tournament" in args, "--keep-state" in args, "--no-export" in args
    st("ZZ TEST STARTED " + " ".join(sys.argv[1:]), first=True)
    if not glob.glob(MASTER + r"\DJI_*.MP4"):
        st("ZZ TEST FAILED: fixture missing — run make-zz-fixture.py first"); return 1
    why = busy()
    if why:
        st("ZZ TEST FAILED: not started — " + why); return 1
    os.makedirs(OUT, exist_ok=True)
    before_real, before_drive = listing(ROOT), listing(DRIVE_DIR, real_only=False)
    saved = snapshot()
    st(f"state saved ({len(saved)} items) -> {BACKUP}")
    fails = []
    try:
        old_test_folders()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", VENOM_TEST="1", PREP_OUT=OUT)
        to_t = float(args[args.index("--timeout") + 1]) if "--timeout" in args else None
        if to_t is not None:
            env["BK_TO_MIN"], env["BK_TO_FALLBACK"] = "8", "15"
        if tourn:
            folders = [make_folder(" A"), make_folder(" B")]
            cmd = [PY, W + r"\run-tournament.py", "--test", "--folders", *folders] + passthru
            stat = W + r"\tournament-status.txt"
        else:
            folders = [make_folder("")]
            project = f"zz test {TS}"
            cmd = [PY, W + r"\run-match.py", "--folder", folders[0], "--project", project,
                   "--export-name", project] + (["--hold-export"] if no_export else []) + passthru
            stat = W + r"\run-match-status.txt"
        st("folders: " + " | ".join(folders))
        if to_t is not None:
            for f_ in folders:
                st(add_timeout(f_, to_t))
        st("running: " + " ".join(os.path.basename(c) if c.endswith(".py") else c for c in cmd[1:]))
        rc = subprocess.run(cmd, cwd=W, env=env, creationflags=NOWIN, timeout=7200).returncode
        tail = open(stat, encoding="utf-8", errors="replace").read().strip().splitlines()
        st("run ended (code %s): %s" % (rc, tail[-1][9:200] if tail else "no status"))
        if rc != 0 or not tail or "STOPPED" in tail[-1]:
            fails.append("run stopped: " + (tail[-1][9:200] if tail else "?"))
        elif not tourn and not no_export:
            ex = wait_export(project, folders[0])
            st(ex)
            if not ex.startswith("EXPORT OK"):
                fails.append(ex)
            else:
                pc = check_pictures(project)
                st(pc)
                if "NOT" in pc:
                    fails.append(pc)
        elif tourn and not no_export:
            for i in range(120):                   # run-tournament exports one after another
                tail = open(stat, encoding="utf-8", errors="replace").read().strip().splitlines()
                if tail and any(k in tail[-1] for k in ("TOURNAMENT EXPORTS DONE", "STOPPED")):
                    break
                time.sleep(30)
            st("tournament: " + (tail[-1][9:200] if tail else "?"))
            if not tail or "EXPORTS DONE" not in tail[-1]:
                fails.append("tournament exports not done: " + (tail[-1][9:200] if tail else "?"))
    except Exception:
        fails.append("harness crashed: " + traceback.format_exc()[-600:])
    finally:
        if not keep_state:
            try:
                restore(saved); st("real state files put back (test copies in " + OUT + r"\state)")
            except Exception:
                fails.append("RESTORE FAILED — copies are in " + BACKUP + ": " + traceback.format_exc()[-300:])
        after_real, after_drive = listing(ROOT), listing(DRIVE_DIR, real_only=False)
        changed = sorted(k for k in set(before_real) | set(after_real) if before_real.get(k) != after_real.get(k))
        dchanged = sorted(k for k in set(before_drive) | set(after_drive)
                          if k in before_drive and before_drive.get(k) != after_drive.get(k))
        if changed:
            fails.append("REAL MATCH FILES CHANGED: " + "; ".join(changed[:10]))
        if dchanged:
            fails.append("DRIVE FILES CHANGED: " + "; ".join(dchanged[:10]))
        st("real match folders untouched: " + ("NO" if changed else "yes") +
           "   Drive folder untouched: " + ("NO" if dchanged else "yes"))
        try:
            st(tidy_after())
        except Exception as e:
            st(f"tidy skipped: {e!r:.120}")
        st("ZZ TEST PASSED" if not fails else "ZZ TEST FAILED: " + " | ".join(fails)[:900])
        with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
    return 0 if not fails else 1


T0 = time.time()
if __name__ == "__main__":
    sys.exit(main())
