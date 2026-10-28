"""
Volleyball Autopilot — prepare the YouTube upload while the export is still rendering.
(2026-09-27, Kenny approved "#5: make the thumbnail while the video exports")

Everything here reads the RAW camera files and the scorekeeper data, never the
export, so it can run the moment the overlay is applied:

  python prep-upload.py text
      -> "<date> <Team1> vs <Opponent> - YouTube text.txt" in the match folder:
         title, description, chapters. Needs youtube-info.json, which
         apply-match.lua writes (set start times exactly as the scoreboard
         shows them, set alignment included).

  python prep-upload.py candidates [count]
      -> _overlay_check/thumb-candidates/cand-01.jpg ... plus contact.jpg
         (numbered grid) — frames spread across the match, from the raw clips.

  python prep-upload.py thumbnail <n | auto>
      (auto, 2026-10-08: picks the candidate with the most player movement —
       each candidate also gets a small frame 0.5 s later; the biggest change
       in the court area = a rally in play. Scores in thumb-candidates\cand.json)
      -> "<date> <Team1> vs <Opponent> - thumbnail.jpg" in the match folder,
         made by make-thumbnail.py from candidate n. The thumbnail crops off the
         bottom 20% of the frame anyway, so using raw footage (no scoreboard)
         looks the same as grabbing it from the finished video.

Runs on Kenny's PC (C:\\Python314 has Pillow; ffmpeg/ffprobe on PATH).
"""
import json, os, re, subprocess, sys, datetime, glob

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
# PREP_INFO / PREP_CAND (2026-10-09, tournament mode): another match's snapshot + its own
# thumbnail choices (run-tournament.py thumbnail <match> <n>); unset = the current match, as before
INFO = os.environ.get("PREP_INFO") or os.path.join(WORK, "youtube-info.json")
CAND_DIR = os.environ.get("PREP_CAND") or os.path.join(WORK, "_overlay_check", "thumb-candidates")
MOT_DIR = os.path.join(CAND_DIR, "motion")
FONTS = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
if not os.path.exists(os.path.join(FONTS, "Gotham Narrow Bold.otf")):
    FONTS = os.path.join(WORK, "_overlay_check", "fonts")
DASH = "\u2013"


def load_info():
    info = json.load(open(INFO, encoding="utf-8"))
    info["folder"] = os.path.dirname(info["matchFile"])
    # Testing: PREP_OUT=<dir> writes the text/thumbnail there instead of the
    # match folder (so a test never overwrites a real thumbnail).
    info["out"] = os.environ.get("PREP_OUT") or info["folder"]
    return info


def base_name(info):
    return f'{info["date"]} {info["team1"]} vs {info["team2"]}'


def ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_text():
    info = load_info()
    t1, t2 = info["team1"], info["team2"]
    sets = [s for s in info["sets"] if s["score1"] or s["score2"]]      # skip an unplayed 0-0 set
    # Sets won = the scorekeeper's own tally (knows the format, point caps / time
    # limits, and unfinished sets) — 2026-09-28. Old files: count set scores.
    ev = info.get("events") or []
    if ev:
        w1, w2 = ev[-1][4], ev[-1][5]
    else:
        w1 = sum(1 for s in sets if s["score1"] > s["score2"])
        w2 = sum(1 for s in sets if s["score2"] > s["score1"])
    d = datetime.date.fromisoformat(info["date"])
    short = d.strftime("%b %d, %Y").replace(" 0", " ")
    long_ = d.strftime("%B %d, %Y").replace(" 0", " ")
    scores = ", ".join(f'{s["score1"]}{DASH}{s["score2"]}' for s in sets)
    # Winner (2026-10-02): the scorekeeper's result — 2-sets-only formats decide a
    # 1-1 match on total points. Old files: by sets.
    r = info.get("result") or {}
    p1 = sum(x["score1"] for x in sets); p2 = sum(x["score2"] for x in sets)
    win = int(r.get("winner", 0) or 0) if r else (1 if w1 > w2 else (2 if w2 > w1 else 0))
    on_points = (r.get("decidedBy") == "points") if r else False
    result = "Won" if win == 1 else ("Lost" if win == 2 else "Tied")
    # 2026-10-04: practice scrimmages (scorekeeper "scrim" / "scrim-15"): sets until time's up
    scrim = str((info.get("format") or {}).get("code") or "").startswith("scrim")
    forced = set(int(x) for x in (info.get("forcedSets") or []))
    kind = " | Scrimmage" if scrim else ""
    # 2026-10-18 (Kenny): titles leave out the result - no Won/Lost, no match or set scores.
    # The result stays in the description.
    # 2026-10-25 (Kenny): our own channel - the title starts with the opponent ("vs X"); the
    # description still says "Home Team 14U vs X"
    # 2026-10-26 (Kenny, after the MYVB tournament): the match folder's event.txt (event + stage,
    # e.g. "MYVB 15U Tier 1 \u00b7 Pool Play") goes into the title and on top of the description;
    # an optional description-note.txt (e.g. a camera-gap note) goes on the line after it.
    def _opt(name):
        try:
            return open(os.path.join(info["folder"], name), encoding="utf-8").read().strip()
        except Exception:
            return ""
    event = _opt("event.txt")
    if event.upper() == "SCRIMMAGE":
        event = ""
    note = _opt("description-note.txt")
    title = f'vs {t2}{kind}' + (f' | {event}' if event else '') + f' | {short}'
    if len(title) > 100:                       # YouTube's limit: drop the stage first, then the event
        title = f'vs {t2}{kind} | {event.split(" \u00b7 ")[0]} | {short}' if event else title
    if len(title) > 100:
        title = f'vs {t2}{kind} | {short}'
    team1_full = "Home Team 14U" if t1 == "Home Team" else t1
    if on_points:
        wname = t1 if win == 1 else t2
        final = (f"{'Scrimmage final' if scrim else 'Final'}: {wname} win on total points {max(p1, p2)}{DASH}{min(p1, p2)} "
                 f"\u00b7 sets {w1}{DASH}{w2}")
    else:
        F = "Scrimmage final" if scrim else "Final"
        final = (f"{F}: {t1} win {w1}{DASH}{w2}" if win == 1
                 else f"{F}: {t2} win {w2}{DASH}{w1}" if win == 2
                 else f"{F}: tied {w1}{DASH}{w2}")

    chapters = [(s["start"], f'Set {s["set"]}') for s in sets]
    # Match summary chapter (bookends, 2026-09-28) — also gives 2-set matches the 3
    # chapters YouTube needs.
    try:
        bk = json.load(open(os.path.join(WORK, "bookends.json"), encoding="utf-8"))
        if os.path.normcase(bk.get("folder", "")) == os.path.normcase(info["folder"]):
            chapters.append((bk["summary"]["start_s"], "Match summary"))
    except Exception:
        pass
    if len(chapters) < 3 and info.get("firstMatchPoint") is not None:
        chapters.append((info["firstMatchPoint"], "Match point"))  # YouTube needs 3+
    # front trim (2026-10-01): chapter times are in the trimmed video
    trim, cuts = 0.0, []
    try:
        if os.path.normcase(bk.get("folder", "")) == os.path.normcase(info["folder"]):
            trim = float(bk.get("trim_s", 0.0))
            cuts = bk.get("cuts", [])
    except Exception:
        pass
    # set-break cuts (2026-10-06): times after a cut move up by the removed stretch;
    # a time inside a removed stretch lands on the cut (where the wipe is)
    def vt(t):
        v = t - trim
        for c in cuts:
            v -= (c["in_s"] - c["out_s"]) if t >= c["in_s"] else max(0.0, t - c["out_s"])
        return max(0.0, v)
    chapters = sorted((vt(t), name) for t, name in chapters)
    kept = []
    for t, name in chapters:  # YouTube: each chapter >= 10 s
        if not kept or t - kept[-1][0] >= 10:
            kept.append((t, name))
    kept[0] = (0, kept[0][1])

    # 2026-10-02 (Kenny): link previews (WhatsApp, iMessage, Facebook) drop the line
    # breaks and show only the first ~100 characters, so line 1 is a complete
    # one-line summary that reads well on its own; the details follow below it.
    summary = f"{final} ({scores}) · {team1_full} vs {t2} · {long_}"
    lines = ([event] if event else []) + ([note] if note else []) + [summary, ""]
    lines += [f'Set {s["set"]}: {s["score1"]}{DASH}{s["score2"]}'
              + (" (time ran out)" if scrim and int(s["set"]) in forced else "") for s in sets]
    lines += ["", f"Full {'scrimmage' if scrim else 'match'} with live scoreboard, filmed in 4K 60fps.", ""]
    lines += [f"{ts(t)} {name}" for t, name in kept]
    desc = "\n".join(lines)

    out = os.path.join(info["out"], base_name(info) + " - YouTube text.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("TITLE\n" + title + "\n\nDESCRIPTION\n" + desc + "\n")
    print(out)
    print("TITLE: " + title)
    print(desc)
    if len(kept) < 3:
        print("*** fewer than 3 chapters — YouTube won't show chapters ***")


def camera_clips(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*")) if re.match(r"DJI_.*\.(mp4|mov)$", os.path.basename(f), re.I)]
    def chap(p):
        m = re.search(r"_(\d{4})_", os.path.basename(p))
        return (int(m.group(1)) if m else 0, os.path.basename(p))
    files.sort(key=chap)
    clips = []
    for f in files:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True)
        clips.append((f, float(r.stdout.strip())))
    return clips


def cmd_candidates(count=9):
    from PIL import Image, ImageDraw
    info = load_info()
    clips = camera_clips(info["folder"])
    total = sum(d for _, d in clips)
    os.makedirs(CAND_DIR, exist_ok=True)
    os.makedirs(MOT_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(CAND_DIR, "*.jpg")) + glob.glob(os.path.join(MOT_DIR, "*.jpg")) \
            + glob.glob(os.path.join(CAND_DIR, "cand.json")):
        os.remove(old)
    # only game play (2026-10-01): from the trimmed start to the final point when known
    lo, hi = 0.0, total
    try:
        bk = json.load(open(os.path.join(WORK, "bookends.json"), encoding="utf-8"))
        if os.path.normcase(bk.get("folder", "")) == os.path.normcase(info["folder"]):
            lo = float(bk.get("trim_s", 0.0)) + 30
            hi = min(total, float(bk["summary"]["final_point_s"]))
    except Exception:
        pass
    if hi - lo < 60:
        lo, hi = 0.0, total
    thumbs = []
    try:
        gaps = [(c["out_s"], c["in_s"]) for c in bk.get("cuts", [])] if lo > 0 else []
    except Exception:
        gaps = []
    for i in range(count):
        t = lo + (hi - lo) * (i + 1) / (count + 1)
        for a, b in gaps:                    # set breaks are cut out of the video (2026-10-06)
            if a - 5 <= t < b + 20:
                t = min(b + 20 + i, hi - 1)
        acc = 0
        for f, d in clips:
            if t < acc + d:
                out = os.path.join(CAND_DIR, f"cand-{i + 1:02d}.jpg")
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t - acc:.3f}", "-i", f,
                                "-frames:v", "1", "-q:v", "2", out], check=True)
                thumbs.append((i + 1, out, t))
                # motion pair for "thumbnail auto" (2026-10-08): small frames at t and t+0.5 s
                for tag, dt in (("a", 0.0), ("b", 0.5)):
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t - acc + dt:.3f}", "-i", f,
                                    "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4",
                                    os.path.join(MOT_DIR, f"m{i + 1:02d}{tag}.jpg")])
                break
            acc += d
    W = 640; H = 360
    cols = 3; rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W, rows * H), "black")
    dr = ImageDraw.Draw(sheet)
    for k, (n, p, t) in enumerate(thumbs):
        im = Image.open(p).convert("RGB").resize((W, H))
        x, y = (k % cols) * W, (k // cols) * H
        sheet.paste(im, (x, y))
        dr.rectangle([x, y, x + 120, y + 34], fill="black")
        dr.text((x + 8, y + 8), f"#{n}  {ts(t)}", fill="white")
    scores = {}
    for n, p, t in thumbs:
        scores[n] = {"t": round(t, 2), "motion": motion_score(n)}
    json.dump(scores, open(os.path.join(CAND_DIR, "cand.json"), "w"), indent=1)
    contact = os.path.join(CAND_DIR, "contact.jpg")
    sheet.save(contact, quality=88)
    print(contact)


def motion_score(n):
    """mean change between the t and t+0.5 s frames in the court area (players moving = rally)"""
    from PIL import Image, ImageChops, ImageStat
    try:
        a, b = (Image.open(os.path.join(MOT_DIR, f"m{n:02d}{x}.jpg")).convert("L") for x in "ab")
        w, h = a.size
        box = (int(w * .15), int(h * .25), int(w * .85), int(h * .80))
        return round(ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean[0], 2)
    except Exception:
        return -1


def auto_pick():
    try:
        sc = json.load(open(os.path.join(CAND_DIR, "cand.json")))
        n = max(sc, key=lambda k: sc[k]["motion"])
        if sc[n]["motion"] > 0:
            return int(n)
    except Exception:
        pass
    return 5


def cmd_thumbnail(n):
    info = load_info()
    if str(n) == "auto":
        n = auto_pick()
    frame = os.path.join(CAND_DIR, f"cand-{int(n):02d}.jpg")
    out = os.path.join(info["out"], base_name(info) + " - thumbnail.jpg")
    r = subprocess.run([sys.executable, os.path.join(WORK, "make-thumbnail.py"),
                        info["matchFile"], frame, out, FONTS], capture_output=True, text=True)
    print(r.stdout + r.stderr)
    if os.path.exists(out):
        print(f"THUMBNAIL: {out} (candidate {n})")


if __name__ == "__main__":
    a = sys.argv[1:] or ["text"]
    if a[0] == "text":
        cmd_text()
    elif a[0] == "candidates":
        cmd_candidates(int(a[1]) if len(a) > 1 else 9)
    elif a[0] == "thumbnail":
        cmd_thumbnail(a[1])
    else:
        print(__doc__)
