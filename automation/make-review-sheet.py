"""
Venom Rebels — review sheet (2026-09-28, Kenny approved).

One image showing ~12-17 key moments of the finished scoreboard, each with its
video time and what the scoreboard SHOULD read there, so Kenny can check a
match in a couple of minutes instead of scrubbing 90 minutes in Resolve.
The same frames are Claude's own verification renders.

  python make-review-sheet.py plan
      reads youtube-info.json (written by apply-match.lua), picks the moments,
      writes _overlay_check\\review\\plan.json  [{frame, sec, label, expect}]
      (prepare-match.py renders one frame per entry as review\\r-<frame>.mp4)

  python make-review-sheet.py sheet
      extracts the frames, crops the scoreboard, writes
      "<match folder>\\<date> <team1> vs <team2> - review sheet.jpg"

Runs on Kenny's PC (C:\\Python314 has Pillow; ffmpeg on PATH).
"""
import json, os, subprocess, sys

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
INFO = os.path.join(WORK, "youtube-info.json")
RDIR = os.path.join(WORK, "_overlay_check", "review")
PLAN = os.path.join(RDIR, "plan.json")
DASH = "\u2013"


def ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


FMT = {"mode": "best", "decider": 15}     # set from youtube-info.json in plan()


def target(set_no):
    return FMT.get("decider", 15) if (FMT.get("mode") == "best" and set_no >= 3) else FMT.get("pts", 25)


def tags_after(ev):
    """(team, 'SET POINT'|'MATCH POINT') showing after this event, same rule as apply-match
    (format-aware since 2026-09-28: only best-of-3 has MATCH POINT)."""
    sec, s, a, b, w1, w2 = ev
    hi, lo = max(a, b), min(a, b)
    if hi >= target(s) and hi - lo >= 2:
        return []
    out = []
    for team, me, them, won in ((1, a, b, w1), (2, b, a, w2)):
        if me + 1 >= target(s) and (me + 1) - them >= 2:
            out.append((team, "MATCH POINT" if (FMT.get("mode") == "best" and won + 1 >= 2) else "SET POINT"))
    return out


def bookends(info):
    """bookends.json (make-bookends.py plan) if it belongs to this match, else None."""
    p = os.path.join(WORK, "bookends.json")
    if not os.path.exists(p):
        return None
    bk = json.load(open(p, encoding="utf-8"))
    same = os.path.normcase(bk.get("folder", "")) == os.path.normcase(os.path.dirname(info["matchFile"]))
    return bk if same else None


def plan():
    info = json.load(open(INFO, encoding="utf-8"))
    FMT.update(info.get("format") or {})
    fps, evs = info["fps"], info["events"]
    t1, t2 = info["team1"].upper(), info["team2"].upper()
    # video end (the scoreboard fades out over the last 0.5 s)
    end_sec = info.get("end") or (evs[-1][0] + 3.0)
    moments = []   # (sec, label)

    def after(i, pad=1.5):
        """a moment shortly after event i, before event i+1 changes anything"""
        t = evs[i][0] + pad
        if i + 1 < len(evs):
            t = min(t, evs[i + 1][0] - 0.3)
        return max(t, evs[i][0] + 0.35)

    # Intro / summary bookends (2026-09-28): full-frame rows + their flags
    bk = bookends(info)
    full = {}      # sec -> expectation text for full-frame rows
    if bk:
        it, sm, stt = bk["intro"], bk["summary"], bk["stats"]
        if it.get("enabled"):
            t = it["start_s"] + max(2.4, it["hold_end"] - 0.3)
            moments.append((t, "Intro card"))
            full[t] = f"Intro card: {t1} vs {t2}, {info['date']} — then it fades out"
        moments.append((bk["intro"]["sb_in"][1] + 0.4, "Scoreboard in"))
        t = sm["start_s"] + 4.0
        moments.append((t, "Match summary"))
        sets_txt = ", ".join(f"{a}{DASH}{b}" for a, b in stt["sets"])
        w1, w2 = stt["won"]
        wn = stt.get("winner", 1 if w1 > w2 else (2 if w2 > w1 else 0))
        tp1, tp2 = stt["total"]
        res = (f"MATCH TIED {w1}{DASH}{w2}" if not wn else
               f"{t1 if wn == 1 else t2} WIN ON POINTS {max(tp1, tp2)}{DASH}{min(tp1, tp2)}"
               if stt.get("decided_by") == "points" else
               f"{t1 if wn == 1 else t2} WIN {max(w1, w2)}{DASH}{min(w1, w2)}")
        full[t] = f"Summary: FINAL {sets_txt}  —  {res}"
        end_sec = bk["export_end_frame"] / fps
        t = max(end_sec - 0.5, sm["start_s"] + 4.2)
        moments.append((t, "End of video" + (" (held last frame)" if sm["hold_frames"] else "")))
        full[t] = "Summary still showing, no scoreboard" + (" — picture frozen (camera had stopped)" if sm["hold_frames"] else "")
    else:
        moments.append((2.0, "Start (after the fade-in)"))
    sets = sorted({e[1] for e in evs})
    for s in sets:
        idx = [i for i, e in enumerate(evs) if e[1] == s]
        if not any(evs[i][2] + evs[i][3] for i in idx):
            continue                      # a set that was started but never played (2026-10-01)
        first, last = idx[0], idx[-1]
        if s > 1:
            moments.append((after(first, 2.0), f"Set {s} starts"))
        for frac in (1 / 3, 2 / 3):
            i = idx[int(len(idx) * frac)]
            moments.append((after(i), f"Set {s}, mid-set"))
        tagged = [i for i in idx if tags_after(evs[i])]
        if tagged:
            i = tagged[0]
            kind = " / ".join(k for tm, k in tags_after(evs[i]))
            moments.append((after(i, 1.0), f"Set {s}: {kind} tag"))
        moments.append((after(last, 1.2), f"Set {s} ends"))
    if not bk:
        moments.append((max(end_sec - 1.0, 0), "End of video (before the fade-out)"))

    # set-break cuts (2026-10-06): a moment inside a removed stretch isn't in the video -
    # show the resume point just after the wipe instead; plus one frame of the wipe itself
    cuts = bk.get("cuts", []) if bk else []
    for c in cuts:
        moments = [((c["in_s"] + 4.5, lab + " (after the cut)") if c["out_s"] <= t < c["in_s"] + 4.0 else (t, lab))
                   for t, lab in moments]
        if c.get("kind") == "timeout":          # 2026-10-19: time-out cuts - last frame before, the panel, the restart
            m_, s_ = int(c["cut_s"]) // 60, int(c["cut_s"]) % 60
            how = "5 s before the serve whistle" if c.get("how") == "whistle" else "no clear whistle: 40 s before the point"
            moments.append((max(0.0, c["out_s"] - 1.3), f"Time-out {c.get('n', '')}: just before the cut ({m_}:{s_:02d} removed)"))
            moments.append((c["in_s"] + 0.9, f"Time-out {c.get('n', '')} wipe"))
            full[c["in_s"] + 0.9] = "Dark diagonal panel with \u201cTIME-OUT\u201d"
            moments.append((c["in_s"] + 4.5, f"Time-out {c.get('n', '')}: play restarts ({how})"))
            continue
        if c.get("kind") == "camera":           # 2026-10-25: camera stopped mid-set (SD card)
            moments.append((max(0.0, c["out_s"] - 1.3), "Camera gap: last frame before the camera stopped"))
            moments.append((c["in_s"] + 0.9, "Camera-gap wipe"))
            full[c["in_s"] + 0.9] = "Dark diagonal panel with \u201cCAMERA TECHNICAL DIFFICULTY\u201d" + (f" / \u201c{c['note']}\u201d" if c.get("note") else "")
            moments.append((c["in_s"] + 4.5, "Camera gap: footage resumes, score jumped"))
            continue
        moments.append((c["in_s"] + 0.9, f"Set-break wipe (set {c['after_set']} \u2192 {c['next_set']})"))
        full[c["in_s"] + 0.9] = f"Dark diagonal panel with \u201cSET {c['next_set']}\u201d and a green line under it"

    def vt(t):
        v = t - (bk.get("trim_s", 0.0) if bk else 0.0)
        for c in cuts:
            v -= (c["in_s"] - c["out_s"]) if t >= c["in_s"] else max(0.0, t - c["out_s"])
        return max(0.0, v)

    moments.sort()
    # Moments after the camera footage ends (camera stopped before the last point,
    # 2026-09-28) can't be checked — the picture is the held last frame there.
    foot_end = (bk["timeline_frames"] / fps) if bk else end_sec
    kept = []
    for t, lab in moments:
        if t not in full and t > foot_end - 0.2:
            continue
        if kept and t - kept[-1][0] < 1.0 and t not in full:
            continue
        kept.append((t, lab))

    rows = []
    for t, lab in kept:
        cur = ([e for e in evs if e[0] <= t] or evs[:1])[-1]
        sec, s, a, b, w1, w2 = cur
        expect = f"SET {s}   {t1} {a} {DASH} {b} {t2}   sets {w1}{DASH}{w2}"
        tg = tags_after(cur)
        if tg:
            expect += "   + " + ", ".join(f"{k} tag ({t1 if tm == 1 else t2})" for tm, k in tg)
        # labels = time in the exported video (front trim + set-break cuts)
        row = {"frame": int(round(t * fps)), "sec": round(t, 2), "label": f"{ts(vt(t))}  {lab}", "expect": expect}
        if t in full:
            row.update({"expect": full[t], "full": True})
        rows.append(row)
    os.makedirs(RDIR, exist_ok=True)
    json.dump(rows, open(PLAN, "w", encoding="utf-8"), indent=1)
    print(f"{len(rows)} moments -> {PLAN}")
    for r in rows:
        print(r["label"], "|", r["expect"])


def sheet():
    from PIL import Image, ImageDraw, ImageFont
    info = json.load(open(INFO, encoding="utf-8"))
    rows = json.load(open(PLAN, encoding="utf-8"))
    folder = os.path.dirname(info["matchFile"])
    out = os.path.join(os.environ.get("PREP_OUT") or folder,
                       f'{info["date"]} {info["team1"]} vs {info["team2"]} - review sheet.jpg')
    fonts = os.path.join(WORK, "Barlow Condensed font")
    def font(size, bold=False):
        for name in (("BarlowCondensed-Bold.ttf" if bold else "BarlowCondensed-Medium.ttf"),
                     "BarlowCondensed-SemiBold.ttf"):
            p = os.path.join(fonts, name)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.truetype("arial.ttf", size)
    CROP = (608, 1628, 3232, 1972)          # scoreboard area on the 4K frame (2026-10-14: board 0.75, was 700,1640,3140,1960)
    TW, TH = 1220, 160
    FW, FH = 1220, 686                      # full-frame rows (intro / summary), 16:9
    LW, PAD = 420, 14
    bk = bookends(info)
    W = LW + TW + PAD * 3
    flags = []                               # wrapped to the sheet width
    meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    for fl in (bk["flags"] if bk else []):
        cur = "• "
        for w in fl.split():
            if meas.textlength(cur + " " + w, font=font(26)) > W - 3 * PAD and cur.strip():
                flags.append(cur); cur = "   " + w
            else:
                cur = cur + ("" if cur.endswith(" ") else " ") + w
        flags.append(cur)
    HEAD = 120 + (46 + 36 * len(flags) if flags else 0)
    H = HEAD + sum((FH if r.get("full") else TH) + PAD for r in rows) + PAD
    img = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(img)
    d.text((PAD, 14), f'{info["team1"]} vs {info["team2"]}  —  {info["date"]}  —  review sheet', fill="white", font=font(40, True))
    note = "Each row: the picture on the right should match the grey text under the time."
    if bk and bk.get("trim_note"):
        note += "   (" + bk["trim_note"].capitalize() + ")"
    d.text((PAD, 66), note, fill=(170, 170, 170), font=font(26))
    if flags:
        d.text((PAD, 116), "PLEASE LOOK AT:", fill=(255, 200, 60), font=font(30, True))
        for k, fl in enumerate(flags):
            d.text((PAD, 156 + 36 * k), fl, fill=(255, 200, 60), font=font(26))
    # 2026-10-26 perf: the 4K frames are decoded in parallel (4 at a time) and as 8-bit RGB
    # (a 10-bit source made ffmpeg write 33 MB 16-bit PNGs, ~1 s each, one after another)
    from concurrent.futures import ThreadPoolExecutor
    def to_png(r):
        png = os.path.join(RDIR, f'r-{r["frame"]}.png')
        mp4 = os.path.join(RDIR, f'r-{r["frame"]}.mp4')
        if not os.path.exists(png) and os.path.exists(mp4):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-frames:v", "1", "-pix_fmt", "rgb24", png])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(to_png, rows))
    missing = 0
    y = HEAD
    for r in rows:
        th = FH if r.get("full") else TH
        png = os.path.join(RDIR, f'r-{r["frame"]}.png')
        mp4 = os.path.join(RDIR, f'r-{r["frame"]}.mp4')
        if not os.path.exists(png) and os.path.exists(mp4):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-frames:v", "1", png])
        if os.path.exists(png):
            im = Image.open(png).convert("RGB")
            tile = im.resize((FW, FH), Image.LANCZOS) if r.get("full") else im.crop(CROP).resize((TW, TH), Image.LANCZOS)
            img.paste(tile, (LW + PAD * 2, y))
        else:
            missing += 1
            d.rectangle([LW + PAD * 2, y, LW + PAD * 2 + TW, y + th], outline=(200, 60, 60), width=3)
            d.text((LW + PAD * 3, y + 60), "frame missing", fill=(200, 60, 60), font=font(30))
        size = 32
        while size > 20 and d.textlength(r["label"], font=font(size, True)) > LW - 6:
            size -= 2
        d.text((PAD, y + 10), r["label"], fill="white", font=font(size, True))
        # wrap the expectation over up to 3 lines
        words, lines, cur = r["expect"].split(), [], ""
        for w in words:
            if d.textlength(cur + " " + w, font=font(24)) > LW - 10 and cur:
                lines.append(cur); cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        for k, ln in enumerate(lines[:4] if r.get("full") else lines[:3]):
            d.text((PAD, y + 56 + k * 30), ln, fill=(185, 185, 185), font=font(24))
        y += th + PAD
    img.save(out, quality=90)
    print(out, f"({len(rows)} rows, {missing} missing)")


if __name__ == "__main__":
    a = sys.argv[1:] or ["plan"]
    {"plan": plan, "sheet": sheet}.get(a[0], lambda: print(__doc__))()
