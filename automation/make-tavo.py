"""
Venom Rebels — game-play-only video for TAVO (AI stats), 2026-09-28 (Kenny approved).

TAVO's season budget is 120 hours of video and 20 GB per upload, so this makes a
separate, trimmed 1080p file straight from the camera files (no Resolve, no
scoreboard, no intro/summary):

  * each set runs from 1 minute before its first point to 5 seconds after its
    last point; the set breaks in between are cut out (overlapping pieces merge)
  * 1920x1080, same frame rate as the camera (59.94), H.264 ~12 Mbps (~5.4 GB/hour),
    camera audio AAC 160k, fast-start MP4
  * output: <match folder>\\<date> <team1> vs <team2> - TAVO.mp4
    Kenny uploads it to TAVO himself.

  C:\\Python314\\python.exe make-tavo.py            (uses youtube-info.json from apply-match)
  OFF by default since 2026-10-06 (the coach picks which games go to TAVO): setup runs it
  only with PM_TAVO = True. For an older match later, point it at that match's snapshot:
    env TAVO_INFO=<match folder>\\_workflow\\youtube-info.json  python make-tavo.py
  env TAVO_BEFORE / TAVO_AFTER override the 60 s / 5 s margins (tests only)

Log: tavo-log.txt next to this script ("TAVO READY ..." or "*** TAVO FAILED").
Tries GPU decode+encode first (NVIDIA), falls back to CPU if that fails.
"""
import glob, json, os, re, shutil, subprocess, sys, time

# No console windows for ffmpeg/ffprobe/python helpers on Windows (2026-10-01:
# every call used to flash a black window). Applies to all subprocess calls here.
if os.name == "nt" and not getattr(subprocess.Popen, "_no_window", False):
    class _NoWindowPopen(subprocess.Popen):
        _no_window = True
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _NoWindowPopen


WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
INFO = os.environ.get("TAVO_INFO") or os.path.join(WORK, "youtube-info.json")
LOG = os.path.join(WORK, "tavo-log.txt")
FPS_NUM, FPS_DEN = 60000, 1001
BEFORE = float(os.environ.get("TAVO_BEFORE", 60))    # 1 min before each set's first point (Kenny, 2026-09-28; was 2 min)
AFTER = float(os.environ.get("TAVO_AFTER", 5))
MAX_GB = 19.5


def log(msg, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def ts(sec):
    sec = int(round(sec)); h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def camera_clips(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*")) if re.match(r"DJI_.*\.(mp4|mov)$", os.path.basename(f), re.I)]
    def chap(p):
        m = re.search(r"_(\d{4})_", os.path.basename(p)); return (int(m.group(1)) if m else 0, os.path.basename(p))
    out = []
    for f in sorted(files, key=chap):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                            "-of", "json", f], capture_output=True, text=True)
        out.append((f, int(json.loads(r.stdout)["streams"][0]["nb_frames"]) * FPS_DEN / FPS_NUM))
    return out


def segments(ev, E):
    """[start, end] video seconds per set, merged where they overlap."""
    segs = []
    for s in sorted({e[1] for e in ev}):
        pts = [e[0] for e in ev if e[1] == s and e[2] + e[3] > 0]      # real points only (not the 0-0 set start)
        if pts:
            segs.append([max(0.0, pts[0] - BEFORE), min(E, pts[-1] + AFTER)])
    if not segs:
        return [[0.0, E]]
    merged = [segs[0]]
    for a, b in segs[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def pieces(segs, clips):
    """split timeline segments into (file, in, out) per camera file"""
    out, t0 = [], 0.0
    for f, d in clips:
        for a, b in segs:
            lo, hi = max(a, t0), min(b, t0 + d)
            if hi - lo > 0.05:
                out.append((f, lo - t0, hi - t0))
        t0 += d
    return out


def encode(src, a, b, dst, gpu):
    common = ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
              "-b:v", "12M", "-maxrate", "16M", "-bufsize", "24M", "-g", "120", "-profile:v", "high",
              "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", dst]
    vf = os.environ.get("TAVO_VF")  # optional picture tweak (zoom/brightness), CPU filters after GPU decode (2026-10-06)
    if vf:
        cmd = ["ffmpeg", "-y", "-v", "error"] + (["-hwaccel", "cuda"] if gpu else []) + [
               "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", src, "-vf", vf + ",format=yuv420p"] + common
    elif gpu:
        cmd = ["ffmpeg", "-y", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
               "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", src, "-vf", "scale_cuda=1920:1080:format=nv12"] + common
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", src,
               "-vf", "scale=1920:1080:flags=bicubic,format=yuv420p"] + common
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    info = json.load(open(INFO, encoding="utf-8"))
    folder = os.path.dirname(info["matchFile"])
    out = os.path.join(folder, f'{info["date"]} {info["team1"]} vs {info["team2"]} - TAVO{os.environ.get("TAVO_SUFFIX", "")}.mp4')
    # never overwrite a TAVO file (2026-10-06): an existing one -> " v2", " v3", ...
    k = 2
    while os.path.exists(out):
        out = os.path.join(folder, f'{info["date"]} {info["team1"]} vs {info["team2"]} - TAVO v{k}.mp4'); k += 1
    log(f"make-tavo: {folder}", "w")
    clips = camera_clips(folder)
    E = sum(d for _, d in clips)
    segs = segments(info["events"], E)
    keep = sum(b - a for a, b in segs)
    log("keeping " + ", ".join(f"{ts(a)}–{ts(b)}" for a, b in segs)
        + f" = {ts(keep)} of {ts(E)} recorded (cut {ts(E - keep)})")
    tmp = os.path.join(folder, "_tavo_tmp")
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    t0 = time.time()
    gpu = True
    parts = []
    for k, (f, a, b) in enumerate(pieces(segs, clips)):
        dst = os.path.join(tmp, f"p{k:03d}.mp4")
        r = encode(f, a, b, dst, gpu)
        if r.returncode != 0 and gpu:
            log("GPU path failed, using CPU decode: " + r.stderr.strip()[-200:])
            gpu = False
            r = encode(f, a, b, dst, gpu)
        if r.returncode != 0:
            log("*** TAVO FAILED encoding " + os.path.basename(f) + ": " + r.stderr.strip()[-400:])
            return 1
        parts.append(dst)
        log(f"  piece {k + 1}: {os.path.basename(f)} {a:.1f}–{b:.1f} s")
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for p in parts:
            fh.write("file '" + p.replace("'", "'\\''") + "'\n")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                        "-movflags", "+faststart", out], capture_output=True, text=True)
    if r.returncode != 0:
        log("*** TAVO FAILED joining: " + r.stderr.strip()[-400:])
        return 1
    shutil.rmtree(tmp, ignore_errors=True)
    p = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height",
                                   "-of", "json", out], capture_output=True, text=True).stdout)
    dur, gb = float(p["format"]["duration"]), int(p["format"]["size"]) / 1e9
    v = [s for s in p["streams"] if s.get("width")][0]
    ok = abs(dur - keep) < 1.5 and v["width"] == 1920 and v["height"] == 1080 and gb < MAX_GB
    log(f"{os.path.basename(out)}: {ts(dur)} ({dur:.1f} s, expected {keep:.1f}), {gb:.2f} GB, "
        f"{v['codec_name']} {v['width']}x{v['height']}, {'GPU' if gpu else 'CPU'}, {time.time() - t0:.0f} s")
    log(("TAVO READY — " if ok else "*** TAVO CHECK FAILED — ") + out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
