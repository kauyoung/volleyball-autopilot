"""
Volleyball Autopilot - team setup (2026-11-22).

Turns the published scripts (this repo's automation folder, with placeholders like "Home Team", YOURNAME,
E:\\Volleyball Matches) into a working copy for YOUR team and PC. The repo folder is never changed, so you can
re-run this any time (new season playlist, new colours, after a `git pull`).

    python team-setup.py --config team-config.json          # writes the working folder named in the config
    python team-setup.py --config team-config.json --check  # only checks the PC (nothing written)

Start from team-config.example.json (copy it to team-config.json and fill it in) - or let Claude ask you the
questions: the Volleyball Autopilot skill (skill/volleyball-autopilot/SKILL.md) runs this for you.
Prints one "SETUP OK ..." / "SETUP NEEDS ..." summary; every check line starts with OK / MISSING / NOTE.
"""
import argparse, json, ntpath, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = (".py", ".lua", ".js", ".json", ".html", ".css", ".txt", ".md", ".gs")
SKIP = {"README.md", "team-config.json", "team-config.example.json", "team-setup.py"}
DEF_TEAM, DEF_OPP = (112, 213, 73), (107, 189, 255)        # the published colours (#70D549 / #6BBDFF)


def hex_rgb(h):
    h = h.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise SystemExit(f"SETUP NEEDS a colour like #70D549, not '{h}'")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colour_subs(old, new):
    """every form a colour takes in the scripts: hex, 'r, g, b' (tuples, rgba), Lua 0..1 floats"""
    oh, nh = "%02x%02x%02x" % old, "%02x%02x%02x" % new
    subs = [(re.compile(oh, re.I), lambda m: nh.upper() if m.group(0).isupper() else nh),
            (re.compile(r"\b%d,(\s*)%d,(\s*)%d\b" % old), lambda m: f"{new[0]},{m.group(1)}{new[1]},{m.group(2)}{new[2]}")]
    fl = [f"{c / 255:.3f}" for c in new]
    if old == DEF_TEAM:
        lua = r"0\.439,(\s*)0\.835,(\s*)0\.286"
    else:
        lua = r"0\.42,(\s*)0\.74,(\s*)1\.00?"
    subs.append((re.compile(lua), lambda m: f"{fl[0]},{m.group(1)}{fl[1]},{m.group(2)}{fl[2]}"))
    return subs


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load(path):
    c = json.load(open(path, encoding="utf-8"))
    need = ["team_name", "age_group", "short_code", "work_folder", "footage_drive", "google_my_drive",
            "youtube_channel_name", "youtube_playlist_title"]
    miss = [k for k in need if not str(c.get(k) or "").strip()]
    if miss:
        raise SystemExit("SETUP NEEDS these in the config: " + ", ".join(miss))
    for k in ("footage_drive", "archive_drive"):
        c[k] = (c.get(k) or "").strip().rstrip(":\\/").upper()
    if len(c["footage_drive"]) != 1:
        raise SystemExit("SETUP NEEDS footage_drive as one letter, e.g. E")
    if c["short_code"] and len(c["short_code"]) > 8:
        raise SystemExit("SETUP NEEDS short_code of at most 8 letters (it shows on the FINAL screen)")
    return c


def find_tools(c):
    py = c.get("python") or sys.executable
    ffb = c.get("ffmpeg_bin") or ""
    if not ffb:
        w = shutil.which("ffmpeg")
        ffb = ntpath.dirname(w) if w else r"C:\ffmpeg\bin"
    return py, ffb.rstrip("\\/")


def replacements(c, py, ffb):
    work = c["work_folder"].rstrip("\\/")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "YOURNAME"
    team, age, short = c["team_name"].strip(), c["age_group"].strip(), c["short_code"].strip().upper()
    full = f"{team} {age}".strip()
    E, J = c["footage_drive"], c.get("archive_drive") or ""
    gd = c["google_my_drive"].rstrip("\\/")
    pl, pid = c["youtube_playlist_title"].strip(), (c.get("youtube_playlist_id") or "").strip() or "YOUR_PLAYLIST_ID"
    ch = c["youtube_channel_name"].strip()
    pydir = ntpath.dirname(py)
    R = []
    for old in (r"C:\Users\YOURNAME\scoreboard-pipeline",):
        R += [(old.replace("\\", "\\\\"), work.replace("\\", "\\\\")), (old, work), (old.replace("\\", "/"), work.replace("\\", "/"))]
    R += [(r"C:\Users\YOURNAME\Documents\Resolve Assets\volleyball-serve-icon-bold.png", work + r"\assets\volleyball-serve-icon-bold.png")]
    R += [(r"C:\\Python314\\python.exe", py.replace("\\", "\\\\")), (r"C:\Python314\python.exe", py),
          (r"C:\\Python314", pydir.replace("\\", "\\\\")), (r"C:\Python314", pydir),
          (r"C:\ffmpeg\bin", ffb), (r"C:\\ffmpeg\\bin", ffb.replace("\\", "\\\\")),
          (r"E:\\Volleyball Matches", f"{E}:\\\\Volleyball Matches"), (r"E:\Volleyball Matches", f"{E}:\\Volleyball Matches"),
          ('DEST = "E:\\\\"', f'DEST = "{E}:\\\\"'), ('if L in "ACE":', f'if L in "AC{E}":'),
          ('L in "CEF"', f'L in "C{E}{gd[:1].upper()}"'), ("not C:/E:/F:", f"not C:/{E}:/{gd[:1].upper()}:"),
          (r"F:\\My Drive", gd.replace("\\", "\\\\")), (r"F:\My Drive", gd),
          ('"--expect-channel", AUTO_TEAM', f'"--expect-channel", {json.dumps(ch)}'),
          ('"--expect-channel", "Home Team"', f'"--expect-channel", {json.dumps(ch)}'),
          ("Home Team 14U \\u2013 2026-2027 Season", json.dumps(pl)[1:-1]), ("Home Team 14U \u2013 2026-2027 Season", pl),
          ("YOUR_PLAYLIST_ID", pid),
          ("Home Team 14U", full), ("HOME TEAM", team.upper()), ("Home Team", team), ("home team", team.lower()),
          ("home-team", slug(team)), ('"HOME"', json.dumps(short)), ("YOURNAME", user),
          ('{"Home" if t1 ==', '{' + json.dumps(team.split()[0]) + ' if t1 ==')]
    if J:
        R += [(r"J:\\Volleyball Matches", f"{J}:\\\\Volleyball Matches"), (r"J:\Volleyball Matches", f"{J}:\\Volleyball Matches"),
              ('"archive-matches.py", "J:"', f'"archive-matches.py", "{J}:"'), ('r"\\archive-matches.py", "J:"', f'r"\\archive-matches.py", "{J}:"')]
    return R, work


def one_pass(R):
    """all swaps in ONE pass (longest first), so a value that contains another placeholder is never swapped again"""
    d = {}
    for a, b in R:
        d.setdefault(a, b)
    rx = re.compile("|".join(re.escape(k) for k in sorted(d, key=len, reverse=True)))
    return lambda s: rx.sub(lambda m: d[m.group(0)], s)


def write_tree(c, R, cols, work):
    swap = one_pass(R)
    n = 0
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        rel = os.path.relpath(root, HERE)
        dst_dir = os.path.normpath(os.path.join(work, rel))
        os.makedirs(dst_dir, exist_ok=True)
        for f in files:
            if f in SKIP and rel == ".":
                continue
            src, dst = os.path.join(root, f), os.path.join(dst_dir, f)
            if f.endswith(TEXT):
                s = swap(open(src, encoding="utf-8").read())
                for rx, fn in cols:
                    s = rx.sub(fn, s)
                open(dst, "w", encoding="utf-8", newline="\n").write(s)
            else:
                shutil.copy2(src, dst)
            n += 1
    return n


def logo(c, work):
    lf = (c.get("logo_file") or "").strip()
    os.makedirs(os.path.join(work, "team-logos"), exist_ok=True)
    if not lf:
        return "NOTE no team logo given - intro/FINAL/scoreboard show the team without a badge"
    if not os.path.exists(lf):
        return f"MISSING team logo file {lf}"
    try:
        from PIL import Image
        im = Image.open(lf).convert("RGBA")
        bb = im.getbbox() or (0, 0, im.width, im.height)
        im = im.crop(bb)
        side = int(max(im.size) * 1.1)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
        sq = sq.resize((1024, 1024), Image.LANCZOS)
        sq.save(os.path.join(work, "team-logos", slug(c["team_name"]) + ".png"))
        sq.save(os.path.join(work, "team-logo-square.png"))
        return f"OK team logo -> team-logos\\{slug(c['team_name'])}.png + team-logo-square.png"
    except Exception as e:
        return f"MISSING team logo could not be prepared ({e!r:.80}) - needs Pillow"


def checks(c, py, ffb, work):
    L = []
    def ok(cond, good, bad):
        L.append(("OK " + good) if cond else ("MISSING " + bad))
    def run(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=60)
        except Exception:
            return subprocess.CompletedProcess(args, 1, "", "")
    v = run([py, "-c", "import sys;print(sys.version_info[:2] >= (3, 12))"])
    ok(v.stdout.strip() == "True", f"Python 3.12+ ({py})", f"Python 3.12 or newer at {py} (python.org)")
    for mod, pipn in (("PIL", "pillow"), ("numpy", "numpy"), ("googleapiclient", "google-api-python-client"),
                      ("google_auth_oauthlib", "google-auth-oauthlib")):
        r = run([py, "-c", f"import {mod}"])
        ok(r.returncode == 0, f"Python package {pipn}", f"Python package {pipn}: {py} -m pip install {pipn}")
    ok(os.path.exists(os.path.join(ffb, "ffmpeg.exe")) and os.path.exists(os.path.join(ffb, "ffprobe.exe")),
       f"ffmpeg + ffprobe in {ffb}", f"ffmpeg + ffprobe (ffmpeg.org, unzip to C:\\ffmpeg so the files are in C:\\ffmpeg\\bin)")
    res = r"C:\Program Files\Blackmagic Design\DaVinci Resolve"
    ok(os.path.exists(os.path.join(res, "fusionscript.dll")), "DaVinci Resolve installed", "DaVinci Resolve Studio (blackmagicdesign.com)")
    ok(os.path.isdir(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"),
       "Resolve scripting modules", "Resolve scripting modules (comes with Resolve Studio)")
    L.append("NOTE Resolve Studio is required, with Preferences > System > General > External scripting using = Local")
    fonts = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    ok(any(f.lower().startswith("barlowcondensed") for d in fonts if os.path.isdir(d) for f in os.listdir(d)),
       "Barlow Condensed font", "Barlow Condensed font (Google Fonts) - install SemiBold, Bold, ExtraBold")
    ok(bool(shutil.which("npx")), "Node.js (npx, for the HyperFrames intro/FINAL screens)", "Node.js LTS (nodejs.org) - the intro/FINAL screens render with npx hyperframes")
    for t in ("team-intro", "team-final", "team-wipe"):
        d = os.path.join(work, "hyperframes", t)
        ok(os.path.exists(os.path.join(d, "gsap.min.js")) and os.path.exists(os.path.join(d, "CustomEase.min.js")),
           f"GSAP files in hyperframes\\{t}", f"gsap.min.js + CustomEase.min.js in hyperframes\\{t} (gsap.com, free)")
    E = c["footage_drive"]
    ok(os.path.isdir(f"{E}:\\"), f"footage drive {E}:", f"footage drive {E}: (plug it in or pick another letter)")
    gdir = os.path.join(c["google_my_drive"], "Volleyball Matches \u2013 Scorekeeper")
    ok(os.path.isdir(gdir), f"Google Drive folder {gdir}", f"Google Drive for desktop + a folder 'Volleyball Matches \u2013 Scorekeeper' in My Drive ({gdir})")
    if c.get("archive_drive"):
        ok(os.path.isdir(f"{c['archive_drive']}:\\"), f"archive drive {c['archive_drive']}:", f"archive drive {c['archive_drive']}: (only needed at the end of a match day)")
    api = os.path.join(work, "_youtube-api")
    ok(os.path.exists(os.path.join(api, "client_secret.json")), "YouTube API client_secret.json",
       "YouTube API: _youtube-api\\client_secret.json (Google Cloud > YouTube Data API v3 > OAuth client 'Desktop app')")
    ok(os.path.exists(os.path.join(api, "token-main.json")), "YouTube sign-in (token-main.json)",
       f"YouTube sign-in: {py} yt-upload.py auth --channel main  (sign in yourself and pick '{c['youtube_channel_name']}')")
    if not (c.get("youtube_playlist_id") or "").strip():
        L.append("NOTE no youtube_playlist_id - uploads find the playlist by its title instead")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "team-config.json"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out")                       # testing: write here instead of work_folder (paths inside stay work_folder)
    a = ap.parse_args()
    c = load(a.config)
    py, ffb = find_tools(c)
    R, work = replacements(c, py, ffb)
    lines = []
    if not a.check:
        if os.path.normcase(work) == os.path.normcase(HERE):
            raise SystemExit("SETUP NEEDS a work_folder different from the repo folder (the repo copy stays unchanged)")
        cols = colour_subs(DEF_TEAM, hex_rgb(c.get("team_colour") or "#70D549"))
        if c.get("opponent_colour"):
            cols += colour_subs(DEF_OPP, hex_rgb(c["opponent_colour"]))
        if a.out:
            work = a.out
        n = write_tree(c, R, cols, work)
        for d in ("_overlay_check", "_youtube-api", "team-logos", "assets"):
            os.makedirs(os.path.join(work, d), exist_ok=True)
        icon = os.path.join(HERE, "..", "assets", "volleyball-serve-icon-bold.png")     # the scoreboard's serve ball
        if os.path.exists(icon):
            shutil.copy2(icon, os.path.join(work, "assets", "volleyball-serve-icon-bold.png"))
        for name, body in (("auto-upload.txt", "off\n"),
                           ("alert-config.json", json.dumps({"ntfy_topic": "", "phone_push": False, "pc_sound": True, "pc_popup": True}, indent=1) + "\n")):
            p = os.path.join(work, name)
            if not os.path.exists(p):
                open(p, "w", encoding="utf-8").write(body)
        json.dump(c, open(os.path.join(work, "team-config.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        if os.name == "nt":
            try:
                os.makedirs(f"{c['footage_drive']}:\\Volleyball Matches", exist_ok=True)
            except Exception:
                pass
        left = []
        for root, dirs, files in os.walk(work):
            dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
            for f in files:
                if f.endswith((".py", ".lua", ".js")):
                    s = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                    if "YOURNAME" in s or "Home Team" in s:
                        left.append(os.path.relpath(os.path.join(root, f), work))
        lines.append(f"OK {n} files written to {work} for '{c['team_name']} {c['age_group']}'")
        lines.append(("MISSING placeholders still in: " + ", ".join(left[:8])) if left else "OK no placeholders left")
        lines.append(logo(c, work))
    lines += checks(c, py, ffb, work)
    miss = [l for l in lines if l.startswith("MISSING")]
    print("\n".join(lines))
    print(("SETUP NEEDS " + str(len(miss)) + " thing(s) above (MISSING lines)") if miss else "SETUP OK - next: python zz-test.py (practice run)")
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
