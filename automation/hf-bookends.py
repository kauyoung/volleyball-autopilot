"""
Venom Rebels - HyperFrames intro + FINAL screens (Kenny approved 2026-10-04).

Not run on its own: make-bookends.py "render intro|summary" exec()s this file and
calls render(kind, p, log, logo_for). It writes the SAME files the classic
renderer wrote (<match folder>\\intro-overlay.mov / summary-overlay.mov, 4K
ProRes 4444, premultiplied alpha, exact frame count from bookends.json), so
place-bookends.py and the rest of the workflow are unchanged. Returns True when
the file is written; any problem raises, and make-bookends.py then draws the
classic intro/summary instead (automatic fallback).

Templates: hyperframes\\venom-intro\\ and hyperframes\\venom-final\\ (HTML + GSAP).
Each render writes that folder's match.js (the match data) and copies the
team logos into its logos\\ folder.

Render time savers:
  * Only the moving parts are rendered. The intro template is rendered with a
    0.05 s hold; the real hold (bookends.json "hold_s", 4.2 s normally) is made
    here by repeating one still frame. The FINAL is rendered for 6.9 s (all its
    motion) and its last frame is repeated to the planned length.
  * The raw renders are cached in hyperframes\\_renders\\ with the data they were
    made from; a re-run for the same match skips straight to the ~20 s assembly.
"""
import datetime, hashlib, json, os, re, shutil, subprocess, time

WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
HF = os.path.join(WORK, "hyperframes")
RAW = os.path.join(HF, "_renders")
NPX = r"C:\Program Files\nodejs\npx.cmd"
HF_PKG = "hyperframes@0.8.114"        # pinned: the version the templates were approved on
WORKERS = "4"                         # per render; intro + FINAL render at the same time
FPS_NUM, FPS_DEN = 60000, 1001
FPS = FPS_NUM / FPS_DEN

# Intro timing (seconds, at TEMPO 1.7 in motion.js). Keep in step with make-bookends.py.
BUILD_S = 3.145                       # everything on screen ((1.4 + ENTER 0.45) x 1.7)
RAW_HOLD_S = 0.05                     # hold baked into the template (motion.js INTRO_HOLD)
EXIT_S = 1.7                          # exit, panel gone by ~1.45 s

ENC = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
       "-vendor", "apl0", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
# HyperFrames writes straight alpha; Resolve is told the clips are premultiplied
# (place-bookends.py, same as the classic clips), so premultiply here.
TO_OUT = "format=gbrap16le,premultiply=inplace=1,scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le"
NOWIN = 0x08000000


# ------------------------------------------------------------------ DATA
def _season(date):
    y, m = int(date[:4]), int(date[5:7])
    a = y if m >= 8 else y - 1
    return f"{a}\u2013{(a + 1) % 100:02d}"


def _date(date):
    return datetime.date.fromisoformat(date).strftime("%a, %b %d, %Y").upper().replace(" 0", " ")


def _format(info):
    f = info.get("format") or {}
    # the scorekeeper's 4 format codes first (older match files lack "sets" or "pts")
    code = str(f.get("code") or "")
    m = re.match(r"^(bo3|2of2|scrim)(-15)?$", code)
    if m and m.group(1) == "scrim":       # 2026-10-04: practice scrimmage, sets until time's up
        return "SCRIMMAGE", f"SETS TO {15 if m.group(2) else 25}"
    if m:
        return ("BEST OF 3" if m.group(1) == "bo3" else "2 SETS"), f"SETS TO {15 if m.group(2) else 25}"
    sets, pts = f.get("sets"), f.get("pts")
    fmt = ((f"{sets} SETS" if f.get("mode") == "all" else f"BEST OF {sets}") if sets else "")
    return fmt, (f"SETS TO {pts}" if pts else "")


def event_name(folder):
    """The tournament / event name Kenny gives at the start of the workflow (2026-10-06),
    saved by prepare-match.py setup as <match folder>\\event.txt. '' when none."""
    try:
        return open(os.path.join(folder, "event.txt"), encoding="utf-8").read().strip().upper()
    except Exception:
        return ""


def _names():
    clubs, overrides = [], {}
    try:
        for line in open(os.path.join(WORK, "team-logos", "intro-names.txt"), encoding="utf-8"):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.lower().startswith("club:"):
                clubs.append(s[5:].strip())
            elif "=" in s:
                a, b = s.split("=", 1)
                overrides[a.strip()] = b.strip()
    except FileNotFoundError:
        pass
    return clubs, overrides


def _mmss(sec):
    t = int(round(sec))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# 2026-10-21 (Kenny): logos must LOOK the same size on the intro / FINAL too. The
# templates show the whole image ("contain"), so padding in a PNG made a logo smaller.
# Each logo is copied as a square whose VISIBLE drawing (logo_sizes.ink_box, near-black
# left out) is LOGO_FILL of the height x its optical factor (team-logos\logo-sizes.txt),
# centred. The file name carries a hash, so a changed logo/factor re-renders the cache.
LOGO_FILL, LOGO_MAX_W = 0.78, 0.86


def _norm_logo(src, logos_dir):
    import sys
    if WORK not in sys.path:
        sys.path.insert(0, WORK)
    import logo_sizes
    from PIL import Image
    W0, H0, x0, y0, x1, y1 = logo_sizes.ink_box(src)
    f = logo_sizes.factor(src)
    tag = hashlib.sha1(f"{os.path.getmtime(src)}|{os.path.getsize(src)}|{f}|{LOGO_FILL}|{LOGO_MAX_W}|v1".encode()).hexdigest()[:8]
    stem = os.path.splitext(os.path.basename(src))[0].lower()
    name = f"{stem}-{tag}.png"
    dst = os.path.join(logos_dir, name)
    if not os.path.exists(dst):
        vw, vh = max(1, x1 - x0), max(1, y1 - y0)
        side = max(vh / (LOGO_FILL * f), vw / LOGO_MAX_W)
        im = Image.open(src).convert("RGBA")
        k = min(1.0, 1024 / side)                       # keep the copy <= 1024 px
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        S = max(1, round(side * k))
        can = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        can.paste(im, (round(S / 2 - (x0 + x1) / 2 * k), round(S / 2 - (y0 + y1) / 2 * k)), im)
        can.save(dst)
        for old in os.listdir(logos_dir):               # tidy older copies of the same logo
            if old != name and re.fullmatch(re.escape(stem) + r"-[0-9a-f]{8}\.png", old):
                try:
                    os.remove(os.path.join(logos_dir, old))
                except OSError:
                    pass
    return name


def build_data(kind, p, logo_for, tdir):
    info = json.load(open(os.path.join(WORK, "youtube-info.json"), encoding="utf-8"))
    fmt, detail = _format(info)
    clubs, overrides = _names()
    os.makedirs(os.path.join(tdir, "logos"), exist_ok=True)

    def team(name):
        lg = logo_for(name)
        if lg and os.path.exists(lg):
            try:
                return {"name": name, "logo": "logos/" + _norm_logo(lg, os.path.join(tdir, "logos"))}
            except Exception as e:
                print(f"logo sizing skipped for {name}: {e}")
            dst = os.path.join(tdir, "logos", os.path.basename(lg))
            if not os.path.exists(dst) or os.path.getmtime(dst) != os.path.getmtime(lg):
                shutil.copy2(lg, dst)
            return {"name": name, "logo": "logos/" + os.path.basename(lg)}
        return {"name": name, "logo": None}

    d = {"season": _season(p["date"]), "team1": team(p["team1"]), "team2": team(p["team2"]),
         "date": _date(p["date"]), "format": fmt, "detail": detail, "clubs": clubs, "overrides": overrides}
    if kind == "summary":
        # 2026-10-06 (Kenny): the FINAL screen's bottom line is "date \u00b7 event" \u2014 no
        # "BEST OF 3 \u00b7 SETS TO 25" (obvious from the table). No event given: a
        # scrimmage still says SCRIMMAGE, a match shows the date alone.
        ev = event_name(os.path.dirname(info["matchFile"]))
        d.update({"format": ev or ("SCRIMMAGE" if fmt == "SCRIMMAGE" else ""), "detail": ""})
        st = p["stats"]
        d.update({"sets": st["sets"], "won": st["won"], "winner": st.get("winner", 0),
                  "decidedBy": st.get("decided_by", "sets"), "total": st["total"], "run": st["run"],
                  "lead": st["lead"], "matchTime": _mmss(st["match_time"])})
    return d


# ---------------------------------------------------------------- RENDER
def _tree_hash(tdir):
    h = hashlib.sha1()
    for f in sorted(os.listdir(tdir)):
        if f.endswith((".html", ".js", ".css")) and f != "match.js":
            h.update(f.encode()); h.update(open(os.path.join(tdir, f), "rb").read())
    return h.hexdigest()


def _frames(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
                       capture_output=True, text=True, creationflags=NOWIN)
    return int(r.stdout.strip() or 0)


def _raw(kind, data, log):
    """render (or reuse) the template's moving part -> path, frame count"""
    tdir = os.path.join(HF, "venom-intro" if kind == "intro" else "venom-final")
    os.makedirs(RAW, exist_ok=True)
    out = os.path.join(RAW, f"{kind}-raw.mov")
    key = hashlib.sha1((json.dumps(data, sort_keys=True) + _tree_hash(tdir)).encode()).hexdigest()
    keyf = out + ".key"
    if os.path.exists(out) and os.path.exists(keyf) and open(keyf).read() == key:
        n = _frames(out)
        if n:
            log(f"{kind}: reusing the render already made for this match ({n} frames)")
            return out, n
    for f in (out, keyf):
        if os.path.exists(f):
            os.remove(f)
    open(os.path.join(tdir, "match.js"), "w", encoding="utf-8").write(
        "// written by hf-bookends.py for this match\nwindow.MATCH = " + json.dumps(data, ensure_ascii=False) + ";\n")
    env = dict(os.environ, HYPERFRAMES_SKIP_SKILLS="1", NO_COLOR="1")
    t0 = time.time()
    # The templates are laid out at 3840x2160 (#scene zoom 2), so Chrome draws 4K
    # directly and the fast drawElement capture can run (measured 2026-10-04 on the
    # PC: intro 39 s vs 73 s with --resolution 4k upscaling; identical pictures).
    r = subprocess.run([NPX, "--yes", HF_PKG, "render", "--fps", f"{FPS_NUM}/{FPS_DEN}", "--format", "mov",
                        "--workers", WORKERS, "--experimental-fast-capture=true", "--quiet", "--output", out],
                       cwd=tdir, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=900, creationflags=NOWIN)
    n = _frames(out) if os.path.exists(out) else 0
    if r.returncode != 0 or not n:
        tail = " ".join(((r.stdout or "") + (r.stderr or "")).split())[-300:]
        raise RuntimeError(f"HyperFrames render stopped (code {r.returncode}): {tail}")
    open(keyf, "w").write(key)
    log(f"{kind}: HyperFrames render {n} frames in {time.time() - t0:.0f} s")
    return out, n


def _ffmpeg(args, n_expected, out):
    tmp = out[:-4] + ".part.mov"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + args + ["-frames:v", str(n_expected), "-r", f"{FPS_NUM}/{FPS_DEN}"]
                       + ENC + [tmp], capture_output=True, text=True, creationflags=NOWIN)
    got = _frames(tmp) if os.path.exists(tmp) else 0
    if r.returncode != 0 or got != n_expected:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(f"assembling stopped: wrote {got} of {n_expected} frames ({(r.stderr or '')[-200:]})")
    try:
        os.replace(tmp, out)
    except OSError:
        os.remove(tmp)
        raise RuntimeError(f"{os.path.basename(out)} is in use (already placed in Resolve?) - remove it from the timeline and media pool, then render again")


def render(kind, p, log, logo_for):
    t0 = time.time()
    tdir = os.path.join(HF, "venom-intro" if kind == "intro" else "venom-final")
    if not os.path.isdir(tdir):
        raise RuntimeError(f"template folder missing: {tdir}")
    if kind == "intro":
        it = p["intro"]
        out = os.path.join(p["folder"], "intro-overlay.mov")
        if not it["enabled"]:
            if os.path.exists(out):
                os.remove(out)
            log("INTRO SKIPPED")
            return True
        raw, m = _raw("intro", build_data("intro", p, logo_for, tdir), log)
        n = it["n_frames"]
        k = int(round((BUILD_S + RAW_HOLD_S / 2) * FPS))        # a frame inside the baked-in hold
        extra = n - m
        if extra < 0:
            raise RuntimeError(f"planned intro ({n} frames) is shorter than its animation ({m})")
        _ffmpeg(["-i", raw, "-vf", f"loop=loop={extra}:size=1:start={k},setpts=N/FRAME_RATE/TB," + TO_OUT], n, out)
        log(f"INTRO READY (HyperFrames, {n} frames, hold {it.get('hold_s', 0):.1f} s, {time.time() - t0:.0f} s) \u2014 {out}")
        return True

    sm = p["summary"]
    out = os.path.join(p["folder"], "summary-overlay.mov")
    raw, m = _raw("summary", build_data("summary", p, logo_for, tdir), log)
    n, hold = sm["n_frames"], sm.get("hold_frames", 0)
    pad = max(0, n - m)
    base = f"tpad=stop_mode=clone:stop={pad},setpts=N/FRAME_RATE/TB"
    if hold <= 0:
        _ffmpeg(["-i", raw, "-vf", base + "," + TO_OUT], n, out)
    else:
        # camera stopped before the summary ended: the last camera frame sits under
        # the screen for the frames past the footage (the classic summary did the same)
        last_clip = p["clips"][-1][0]
        png = os.path.join(RAW, "last-frame.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-1", "-i", last_clip, "-update", "1", png],
                       creationflags=NOWIN)
        a = n - hold
        fc = (f"[0:v]{base},format=rgba,split[x][y];[x]trim=end_frame={a},setpts=PTS-STARTPTS[a];"
              f"[y]trim=start_frame={a},setpts=PTS-STARTPTS[b];"
              f"[1:v]scale=3840:2160,format=rgba,trim=end_frame={hold},setpts=N/FRAME_RATE/TB[bg];"
              f"[bg][b]overlay=format=auto,format=rgba[c];[a][c]concat=n=2:v=1,setpts=N/FRAME_RATE/TB," + TO_OUT)
        _ffmpeg(["-i", raw, "-loop", "1", "-framerate", f"{FPS_NUM}/{FPS_DEN}", "-i", png, "-filter_complex", fc], n, out)
    log(f"SUMMARY READY (HyperFrames, {n} frames, {hold} held, {time.time() - t0:.0f} s) \u2014 {out}")
    return True
