"""
Home Team - set-break / time-out / camera wipes (2026-11-12 motion redo, the owner "implement this").

The wipes are now drawn by HyperFrames from hyperframes\\team-wipe (the same 14-degree panel
system as the intro and FINAL screens: edge bands that stretch with speed, the words printed
on the panel, faint hairlines that drift the whole time). One render = 173 frames, cut into
  set-wipe\\wipe-in-<id>.mov    frames 0-52   (0.8 s sweep + 5 covered frames)
  set-wipe\\wipe-out-<id>.mov   frames 53-172 (1.2 s covered, then 0.8 s sweep off)
- the same lengths, file names and set-wipe.json fields as before, so place-bookends.py,
fix-audio.py, prepare-match.py and run-match.py are unchanged. 4K ProRes 4444, premultiplied.
  C:\\Python314\\python.exe make-set-wipe.py [2 3 4 ...] [timeout] [force]
      (default sets 2-5; existing clips are skipped unless "force")
Log: set-wipe\\set-wipe-log.txt ("WIPE READY"). set-wipe.json lists what exists.
make-camera-wipe.py uses make() from here. The old Pillow version: _backup-2026-11-12-motion-redo\\.
"""
import json, os, shutil, subprocess, sys, time

WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
OUT = os.path.join(WORK, "set-wipe")
LOG = os.path.join(OUT, "set-wipe-log.txt")
META = os.path.join(OUT, "set-wipe.json")
TEMPLATE = os.path.join(WORK, "hyperframes", "team-wipe")
NPX = r"C:\Program Files\nodejs\npx.cmd"
HF_PKG = "hyperframes@0.8.114"              # pinned, same as hf-bookends.py
VERSION = 4                                 # 4 = HyperFrames panel (2026-11-12); 3 = Pillow panel
FPS_NUM, FPS_DEN = 60000, 1001
IN_FRAMES, OUT_FRAMES = 53, 120
MOVE_S, HOLD_S = 0.8, 1.2
ENC = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
       "-vendor", "apl0", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
# HyperFrames writes straight alpha; Resolve is told the clips are premultiplied (place-bookends.py)
TO_OUT = "format=gbrap16le,premultiply=inplace=1,scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le"
NOWIN = 0x08000000


def sfx(n):
    """file suffix: set<n>, 'timeout', or a camera label as given"""
    return f"set{n}" if isinstance(n, int) else str(n)


def words(n):
    """what the panel says for a set number or 'timeout'"""
    if n == "timeout":
        return {"label": "TIME-OUT", "ghost": "", "sub": ""}
    return {"label": f"SET {n}", "ghost": str(n), "sub": ""}


def _frames(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
                       capture_output=True, text=True, creationflags=NOWIN)
    return int(r.stdout.strip() or 0)


def _cut(raw, start, count, name):
    path = os.path.join(OUT, name)
    tmp = path[:-4] + ".tmp.mov"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-vf",
                        f"trim=start_frame={start}:end_frame={start + count},setpts=PTS-STARTPTS," + TO_OUT,
                        "-frames:v", str(count), "-r", f"{FPS_NUM}/{FPS_DEN}"] + ENC + [tmp],
                       capture_output=True, text=True, creationflags=NOWIN)
    got = _frames(tmp) if os.path.exists(tmp) else 0
    if r.returncode != 0 or got != count:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(f"{name}: wrote {got} of {count} frames ({(r.stderr or '')[-200:]})")
    os.replace(tmp, path)
    return got


def make(suffix, spec):
    """render one wipe (spec: label / ghost / sub) -> (frames in wipe-in, frames in wipe-out).
    Each render works in its own copy of the template, so two wipes can be made at the same time."""
    if not os.path.isdir(TEMPLATE):
        raise RuntimeError(f"template folder missing: {TEMPLATE}")
    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(OUT, f"_render-{suffix}-{os.getpid()}")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(TEMPLATE, work)
    try:
        open(os.path.join(work, "wipe.js"), "w", encoding="utf-8").write(
            "// written by make-set-wipe.py\nwindow.WIPE = " + json.dumps(spec, ensure_ascii=False) + ";\n")
        raw = os.path.join(work, "raw.mov")
        env = dict(os.environ, HYPERFRAMES_SKIP_SKILLS="1", NO_COLOR="1")
        last = ""
        for fast in (True, False):              # the plain capture is the fallback
            if os.path.exists(raw):
                os.remove(raw)
            cmd = [NPX, "--yes", HF_PKG, "render", "--fps", f"{FPS_NUM}/{FPS_DEN}", "--format", "mov", "--workers", "4"]
            cmd += (["--experimental-fast-capture=true"] if fast else []) + ["--quiet", "--output", raw]
            r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900, creationflags=NOWIN)
            n = _frames(raw) if os.path.exists(raw) else 0
            if r.returncode == 0 and n == IN_FRAMES + OUT_FRAMES:
                break
            last = f"code {r.returncode}, {n} frames: " + " ".join(((r.stdout or "") + (r.stderr or "")).split())[-200:]
        else:
            raise RuntimeError(f"HyperFrames render stopped ({last})")
        return _cut(raw, 0, IN_FRAMES, f"wipe-in-{suffix}.mov"), _cut(raw, IN_FRAMES, OUT_FRAMES, f"wipe-out-{suffix}.mov")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def log(m, mode="a"):
    os.makedirs(OUT, exist_ok=True)
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + m + "\n")


def load_meta():
    """set-wipe.json, emptied when it belongs to an older design"""
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception:
        meta = {}
    if meta.get("version") != VERSION or meta.get("hold_s") != HOLD_S:
        meta = {}
    return meta


def save_meta(meta, have=None):
    if have is not None:
        meta["sets"] = sorted(x for x in have if isinstance(x, int))
        meta["labels"] = sorted(x for x in have if not isinstance(x, int))
    meta.update({"in_frames": IN_FRAMES, "out_frames": OUT_FRAMES, "move_s": MOVE_S, "hold_s": HOLD_S,
                 "version": VERSION, "made": time.strftime("%Y-%m-%d %H:%M")})
    meta.setdefault("sets", []); meta.setdefault("labels", [])
    json.dump(meta, open(META, "w", encoding="utf-8"), indent=1)


def main(sets, force=False):
    os.makedirs(OUT, exist_ok=True)
    meta = load_meta()
    have = set(meta.get("sets", [])) | set(meta.get("labels", []))
    todo = sorted((s for s in sets if force or s not in have
                   or not os.path.exists(os.path.join(OUT, f"wipe-in-{sfx(s)}.mov"))
                   or not os.path.exists(os.path.join(OUT, f"wipe-out-{sfx(s)}.mov"))), key=str)
    if not todo:
        log("WIPE READY (already made: " + ", ".join(map(str, sorted(have, key=str))) + ")", "w")
        return 0
    log("drawing the set-break wipe (HyperFrames): " + ", ".join(map(str, todo)), "w")
    t0 = time.time()
    for s in todo:
        t1 = time.time()
        make(sfx(s), words(s))
        meta = load_meta()                       # a camera wipe may have been added meanwhile
        have = set(meta.get("sets", [])) | set(meta.get("labels", [])) | {s}
        save_meta(meta, have)
        log(f"  {sfx(s)}: {time.time() - t1:.0f} s")
    meta = load_meta()
    log(f"WIPE READY ({len(todo)} wipe(s), {time.time() - t0:.0f} s; sets {', '.join(map(str, meta['sets']))}"
        + (f"; {', '.join(meta.get('labels', []))}" if meta.get("labels") else "") + ")")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    nums = [int(a) for a in args if a.isdigit()] + (["timeout"] if "timeout" in args else [])
    nums = nums or [2, 3, 4, 5]
    try:
        sys.exit(main(nums, "force" in args))
    except Exception as ex:
        log(f"WIPE FAILED: {ex}")
        sys.exit(1)
