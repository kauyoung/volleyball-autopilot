"""
Venom Rebels — intro card + match summary ("bookends"), 2026-09-28 (Kenny approved).

Both play ON TOP of the match video (Kenny records ~15 s before the first serve
and ~30 s after the last point). Each is rendered as a 4K ProRes 4444 clip WITH
ALPHA that goes on video track 3: a blurred + dimmed copy of the match video
(its alpha ramps 0 -> 1, so the cut-in is invisible) plus the animated card.
Design approved on previews (_overlay_check\\mock\\preview-*.mp4):
  intro   = "centre card": logo pops, card opens, VENOM REBELS / VS / opponent
            / neutral grey line / MATCH REPLAY · date; starts 2 s in; smooth
            1.2 s ease-in-out fade-out; scoreboard eases in after it.
  summary = FINAL tab, two team rows (set scores, sets won), "<WINNER> WIN a–b",
            4 stat boxes (total points, longest run, biggest lead, match time),
            date · season footer; starts 15 s after the final point.

  C:\\Python314\\python.exe make-bookends.py plan
      reads youtube-info.json (apply-match.lua) + the match folder's camera clips,
      writes bookends.json (all timings, in seconds and timeline frames) and
      prints any flags. Rules:
        * intro starts 2.0 s in. First-point check: the scoreboard must be fully
          in >= 1 s before the first point is tapped; if not, the intro starts
          earlier (down to 0.5 s) and holds shorter (min 2.6 s); if it still
          doesn't fit, NO intro (the scoreboard fades in at the start as before).
        * summary starts 15 s after the final point (or 1 s before the recording
          ends if the camera stopped sooner). It needs >= 10 s on screen: if the
          recording ends earlier, the last frame is HELD. If the camera ran on,
          the video is ended 12 s into the summary ("export_end").
  C:\\Python314\\python.exe make-bookends.py render intro|summary
      renders "<match folder>\\intro-overlay.mov" / "summary-overlay.mov".
      2026-10-04: these are now the HyperFrames screens (hf-bookends.py, templates in
      hyperframes\\); the classic ones drawn below are the automatic fallback.
      Log: bookends-log.txt ("INTRO READY" / "SUMMARY READY" / "INTRO SKIPPED").
"""
import datetime, glob, json, math, os, re, subprocess, sys, time
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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
PLAN = os.path.join(WORK, "bookends.json")
LOG = os.path.join(WORK, "bookends-log.txt")
FONTS = os.path.join(WORK, "Barlow Condensed font")
LOGOS = os.path.join(WORK, "team-logos")
FPS_NUM, FPS_DEN = 60000, 1001
FPS = FPS_NUM / FPS_DEN
W, H = 3840, 2160
PREMULT = True                     # Resolve reads ProRes 4444 alpha as premultiplied (verified 2026-09-28)
GREEN, BLUE, WHITE, GREY, DIMG = (112, 213, 73), (107, 189, 255), (255, 255, 255), (170, 170, 170), (120, 120, 120)
SEASON = {"Venom Rebels": "VENOM REBELS 14U \u2013 2026-2027 SEASON"}
DASH = "\u2013"

INTRO_AT, INTRO_EARLIEST = 2.0, 0.5
# 2026-10-04 HyperFrames intro (hf-bookends.py): builds in 3.145 s, holds INTRO_HOLD s,
# exits in 1.7 s (panel gone ~1.45 s into the exit). Shorter hold if the first point is early.
INTRO_BUILD, INTRO_HOLD, INTRO_EXIT, INTRO_MIN_HOLD = 3.145, 4.2, 1.7, 2.0
LEAD_IN = float(os.environ.get("BK_LEAD_IN", 60.0))   # video starts this long before the first point
                                                      # (front trim, 2026-10-01; env only for tests)
SUMMARY_AFTER, SUMMARY_MIN, SUMMARY_MAX = 15.0, 10.0, 12.0
# Set-break cuts (2026-10-06, Kenny): the video cuts BREAK_AFTER s after each set's last
# point (not the final set) and resumes BREAK_LEAD s before the next set's first point,
# with the diagonal wipe (make-set-wipe.py) over the join. EVERY set break gets the wipe
# (Kenny, 2026-10-06): when the break is too short to remove anything, the wipe still
# plays at BREAK_AFTER s after the last point (nothing cut), moved earlier if needed so it
# and the scoreboard fade-in finish BREAK_CLEAR s before the first serve; a break shorter
# than BREAK_TOO_SHORT s (camera stopped between sets) gets no wipe. Env overrides are for
# tests only; BK_SET_CUTS=0 turns the cuts off.
BREAK_AFTER = float(os.environ.get("BK_BREAK_AFTER", 10.0))
BREAK_LEAD = float(os.environ.get("BK_BREAK_LEAD", 60.0))
BREAK_MIN = float(os.environ.get("BK_BREAK_MIN", 1.0))    # less than this to remove -> wipe only
BREAK_CLEAR, BREAK_TOO_SHORT = 5.0, float(os.environ.get("BK_BREAK_TOO_SHORT", 8.0))
SET_CUTS = os.environ.get("BK_SET_CUTS", "1") != "0"
# 2026-10-19 (Kenny): restarts end WHISTLE_LEAD s before the referee's serve whistle (whistle.py),
# for set breaks AND time-outs; a whistle counts only if it is >= WHISTLE_MIN_BEFORE s before the
# point tap (otherwise it may be the rally-ending whistle). No whistle -> the old rules
# (set break: BREAK_LEAD s before the first point; time-out: TO_FALLBACK s before the next point).
# Time-outs: one tap in the scorekeeper ("timeouts" in the match file); the cut starts TO_AFTER s
# after the tap; less than TO_MIN s to remove -> left in (no wipe).
WHISTLE_LEAD, WHISTLE_MIN_BEFORE = 5.0, 8.0
TO_AFTER = 5.0
TO_FALLBACK = float(os.environ.get("BK_TO_FALLBACK", 40.0))
TO_MIN = float(os.environ.get("BK_TO_MIN", 20.0))
WHISTLES = os.environ.get("BK_WHISTLES", "1") != "0"


def serve_whistle(clips, lo, hi):
    """timeline seconds of the serve whistle in [lo, hi], or None (never raises)"""
    if not WHISTLES or hi - lo < 1:
        return None
    try:
        sys.path.insert(0, WORK)
        import whistle
        return whistle.serve_whistle([(f, n) for f, n in clips], FPS, lo, hi)
    except Exception as ex:
        log(f"(whistle search failed: {ex!r} — using the fixed rule)")
        return None


def log(msg, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


# ---------------------------------------------------------------------- PLAN
def camera_clips(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*")) if re.match(r"DJI_.*\.(mp4|mov)$", os.path.basename(f), re.I)]
    def chap(p):
        m = re.search(r"_(\d{4})_", os.path.basename(p)); return (int(m.group(1)) if m else 0, os.path.basename(p))
    out = []
    for f in sorted(files, key=chap):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                            "-of", "json", f], capture_output=True, text=True)
        out.append((f, int(json.loads(r.stdout)["streams"][0]["nb_frames"])))
    return out


def plan():
    info = json.load(open(INFO, encoding="utf-8"))
    folder = os.path.dirname(info["matchFile"])
    clips = camera_clips(folder)
    N = sum(n for _, n in clips)
    E = N / FPS
    ev = info["events"]                                   # [sec, set, s1, s2, sets1, sets2]
    # real points only: a score change, never a 0-0 set-start marker (2026-10-01: a
    # 3rd set that was started but never played made its 0-0 the "final point")
    real = [e for i, e in enumerate(ev) if i > 0 and e[2] + e[3] > 0
            and (e[1], e[2], e[3]) != (ev[i - 1][1], ev[i - 1][2], ev[i - 1][3])]
    P1 = real[0][0] if real else E
    F = real[-1][0] if real else E
    flags = []

    # Camera stopped before the match ended (battery, full card, overheating)
    # (2026-09-28): points scored after the footage ends can't be shown. The
    # summary then comes in at the end of the footage over the held last frame.
    lost = [e for e in real if e[0] > E - 0.2]
    if lost:
        flags.append(f"the camera stopped {F - E:.0f} s before the final point — the last {len(lost)} point(s) "
                     "aren't in the video; the summary comes in over the last frame")
        F = min(F, E - 2.5)          # -> summary starts 1 s before the footage ends

    # Camera vs scorekeeper start (2026-09-28): copy-card measures when the camera
    # started vs when START was tapped. A big gap means every score shows up early
    # or late by about that much (or the camera's clock is off).
    try:
        ci = json.load(open(os.path.join(folder, "copy-info.txt"), encoding="utf-8"))
        off = float(ci.get("start_offset_s"))
        try:                       # 2026-10-14: the scores may already be shifted by the match .json's "offset"
            jo = float(json.load(open(info["matchFile"], encoding="utf-8")).get("offset") or 0.0)
        except Exception:
            jo = 0.0
        if abs(off) > 5 and abs(off + jo) > 5:
            flags.append(f"the camera started {abs(off):.0f} s {'after' if off > 0 else 'before'} START was tapped "
                         f"(or the camera clock is off) — check that scores change right after rallies; "
                         f"if they're off by that much, re-apply with that offset")
    except Exception:
        pass

    # Front trim (2026-10-01, Kenny): the video starts LEAD_IN s before the first point;
    # anything earlier (warm-up filler) is cut. Everything below is placed relative to it.
    trim_frame = int(round(max(0.0, P1 - LEAD_IN) * FPS))
    TRIM = trim_frame / FPS
    P1r = P1 - TRIM                                       # first point, seconds into the trimmed video

    # intro + first-point check (times relative to the trimmed start)
    intro = {"enabled": False}
    need_after = 2.0 + 1.0                                # hold end -> scoreboard fully in (+1 s margin)
    for start in (INTRO_AT, INTRO_EARLIEST):
        hold = min(INTRO_HOLD, P1r - need_after - INTRO_BUILD - start)
        if hold >= INTRO_MIN_HOLD:
            intro = {"enabled": True, "start_s": round(TRIM + start, 3), "rel_start_s": start, "hold_s": round(hold, 3)}
            break
    if intro["enabled"]:
        s, h, r = intro["start_s"], intro["hold_s"], intro["rel_start_s"]
        total = INTRO_BUILD + h + INTRO_EXIT
        intro.update({"start_frame": trim_frame + int(round(r * FPS)), "n_frames": int(round(total * FPS)),
                      "hold_end": round(total - 1.6, 3),     # classic (fallback) intro: card fades out here
                      "sb_in": [round(s + INTRO_BUILD + h + 1.3, 3), round(s + INTRO_BUILD + h + 2.0, 3)]})
        if (r, h) != (INTRO_AT, INTRO_HOLD):
            flags.append(f"first point was tapped {P1r:.1f} s in, so the intro was moved to {r:.1f} s and shortened "
                         f"(on screen {total:.1f} s instead of {INTRO_BUILD + INTRO_HOLD + INTRO_EXIT:.1f} s)")
    else:
        flags.append(f"first point was tapped only {P1r:.1f} s in — no room for the intro, so it was left out")
        intro["sb_in"] = [round(TRIM, 3), round(TRIM + 0.5, 3)]

    # summary + hold / trim
    S = F + SUMMARY_AFTER
    if S > E - 1.0:
        S = max(F + 1.5, E - 1.0)
        if not lost:
          flags.append(f"the camera stopped {E - F:.1f} s after the final point (15 s of celebration were planned) — "
                     f"the summary starts {S - F:.1f} s after it")
    end = max(min(E, S + SUMMARY_MAX), S + SUMMARY_MIN)
    hold = max(0.0, end - E)
    if hold > 0:
        flags.append(f"recording ended {E - S:.1f} s into the summary — last frame held {hold:.1f} s")
    # (camera running on past the summary is normal — the export just ends 12 s in)
    s0 = int(round(S * FPS)); e0 = int(round(end * FPS))
    summary = {"start_s": round(S, 3), "start_frame": s0, "n_frames": e0 - s0, "final_point_s": round(F, 3),
               "hold_frames": max(0, e0 - N), "sb_out": [round(S, 3), round(S + 0.5, 3)]}

    # stats
    finals, cur, best, lead = {}, (0, 0), (0, 0), (0, 0)
    prev = None
    for e in ev:
        sec, st, a, b, w1, w2 = e
        finals[st] = (a, b)
        if prev and prev[1] == st:
            t = 1 if a > prev[2] else (2 if b > prev[3] else 0)
            if t:
                cur = (t, cur[1] + 1) if cur[0] == t else (t, 1)
                if cur[1] > best[1]: best = cur
        else:
            cur = (0, 0)
        if abs(a - b) > lead[1]: lead = (1 if a > b else 2, abs(a - b))
        prev = e
    sets = [finals[k] for k in sorted(finals) if finals[k] != (0, 0)]
    # Sets WON come from the scorekeeper's own tally on the last event (2026-09-28):
    # it knows the format (best of 3 / all sets played), sets ended at a point cap
    # or time limit, and an unfinished set after "End match early" (counts for nobody).
    w1, w2 = (ev[-1][4], ev[-1][5]) if ev else (0, 0)
    stats = {"sets": sets, "won": [w1, w2], "total": [sum(a for a, _ in sets), sum(b for _, b in sets)],
             "run": list(best), "lead": list(lead), "match_time": max(0.0, F - ev[0][0])}
    # Who won (2026-10-02): the scorekeeper's result — in the 2-sets-only formats a
    # 1-1 match goes to the team with the most total points. Old files: by sets.
    r = info.get("result") or {}
    win = int(r.get("winner", 0) or 0) if r else (1 if w1 > w2 else (2 if w2 > w1 else 0))
    by = r.get("decidedBy") or ("sets" if win else "tie")
    if not r and w1 == w2 and (info.get("format") or {}).get("mode") == "all" and stats["total"][0] != stats["total"][1]:
        win, by = (1 if stats["total"][0] > stats["total"][1] else 2), "points"
    stats["winner"], stats["decided_by"] = win, by

    # set-break cuts (2026-10-06) - frames on the Match timeline: the video plays up to
    # out_frame (exclusive) and carries on from in_frame
    cuts = []
    sets_seen = []
    for e in real:
        if e[1] not in sets_seen:
            sets_seen.append(e[1])
    for k, nxt in zip(sets_seen, sets_seen[1:]):
        last = [e[0] for e in real if e[1] == k][-1]
        first = [e[0] for e in real if e[1] == nxt][0]
        A, B = last + BREAK_AFTER, first - BREAK_LEAD
        how = "fixed"
        if SET_CUTS and A > TRIM:
            w = serve_whistle(clips, max(A + 2.0, first - 240.0), first - WHISTLE_MIN_BEFORE)
            if w is not None and w - WHISTLE_LEAD > A + BREAK_MIN:
                B, how = w - WHISTLE_LEAD, "whistle"
        if not SET_CUTS or A <= TRIM or B >= F:
            continue
        if B - A < BREAK_MIN:                              # short break: wipe only, nothing cut
            if first - last < BREAK_TOO_SHORT:
                flags.append(f"set {k} \u2192 {nxt}: only {first - last:.0f} s between the last and first point "
                             "(camera stopped?) \u2014 no set-break wipe there")
                continue
            A = B = min(last + BREAK_AFTER, max(last + 2.0, first - BREAK_CLEAR - 4.0))
        a, b = int(round(A * FPS)), int(round(B * FPS))
        cuts.append({"kind": "set", "wipe": f"set{nxt}", "how": how, "after_set": k, "next_set": nxt,
                     "out_frame": a, "in_frame": b,
                     "out_s": round(a / FPS, 3), "in_s": round(b / FPS, 3), "cut_s": round((b - a) / FPS, 3)})
    # time-outs (2026-10-19, Kenny): tap + TO_AFTER s -> WHISTLE_LEAD s before the next serve whistle
    try:
        mj = json.load(open(info["matchFile"], encoding="utf-8"))
        jo = float(mj.get("offset") or 0.0)
        taps = [(float(x["t"]) + jo, int(x.get("set", 0))) for x in (mj.get("timeouts") or [])]
    except Exception:
        taps = []
    n_to = 0
    for T, st_ in sorted(taps):
        nxt_pts = [e[0] for e in real if e[0] > T + 1.0]
        if not nxt_pts:
            continue
        P = nxt_pts[0]
        A = T + TO_AFTER
        w = serve_whistle(clips, A + 1.0, P - WHISTLE_MIN_BEFORE)
        B, how = (w - WHISTLE_LEAD, "whistle") if w is not None else (P - TO_FALLBACK, "fixed")
        n_to += 1
        if any(c["out_s"] - 2 < B and A < c["in_s"] + 2 for c in cuts):
            log(f"time-out {n_to} at {T:.1f} s: falls inside a set break that is already cut - nothing extra")
            continue
        if B - A < TO_MIN or A <= TRIM or B >= F:
            log(f"time-out {n_to} at {T:.1f} s: only {max(0.0, B - A):.0f} s to remove - left in (no wipe)")
            continue
        a, b = int(round(A * FPS)), int(round(B * FPS))
        cuts.append({"kind": "timeout", "wipe": "timeout", "how": how, "n": n_to, "after_set": st_ or None,
                     "next_set": st_ or None, "tap_s": round(T, 3), "next_point_s": round(P, 3),
                     "out_frame": a, "in_frame": b,
                     "out_s": round(a / FPS, 3), "in_s": round(b / FPS, 3), "cut_s": round((b - a) / FPS, 3)})
    cuts.sort(key=lambda c: c["out_frame"])
    cut_total = sum(c["cut_s"] for c in cuts)

    # match time = first point to final point (2026-10-01: the camera now starts minutes
    # early, so "from START" would count the warm-up)
    stats["match_time"] = max(0.0, F - P1)
    if TRIM > 0:
        flags_info = f"trimmed {int(TRIM) // 60}:{int(TRIM) % 60:02d} of warm-up from the start"
    else:
        flags_info = ""
    p = {"fps": FPS, "timeline_frames": N, "export_end_frame": e0, "first_point_s": round(P1, 3),
         "trim_frame": trim_frame, "trim_s": round(TRIM, 3), "trim_note": flags_info,
         "intro": intro, "summary": summary, "stats": stats, "flags": flags,
         "cuts": cuts, "cut_total_s": round(cut_total, 3),
         "team1": info["team1"], "team2": info["team2"], "date": info["date"], "folder": folder,
         "clips": [[f, n] for f, n in clips]}
    json.dump(p, open(PLAN, "w", encoding="utf-8"), indent=1)
    log("bookends plan: intro " + (f"{intro['start_s']} s, holds {intro['hold_s']} s" if intro["enabled"] else "OFF")
        + f"; summary at {S:.1f} s (final point {F:.1f} s); video ends {end:.1f} s (recording {E:.1f} s)"
        + (f"; video starts at {TRIM:.1f} s ({flags_info})" if TRIM > 0 else "; no front trim"), "w")
    for c in cuts:
        if c.get("kind") == "timeout":
            log(f"time-out {c['n']}: cut {c['out_s']:.1f}-{c['in_s']:.1f} s ({int(c['cut_s']) // 60}:{int(c['cut_s']) % 60:02d} removed, "
                + ("restart 5 s before the serve whistle" if c["how"] == "whistle" else f"no clear whistle - kept the last {TO_FALLBACK:.0f} s before the point")
                + ", TIME-OUT wipe over the join)")
            continue
        if c["cut_s"] > 0:
            log(f"set break: set {c['after_set']} -> {c['next_set']}: cut {c['out_s']:.1f}-{c['in_s']:.1f} s "
                + ("[restart 5 s before the serve whistle] " if c.get("how") == "whistle" else "[no clear whistle - 60 s before the first point] ")
                + f"({int(c['cut_s']) // 60}:{int(c['cut_s']) % 60:02d} removed, wipe over the join)")
        else:
            log(f"set break: set {c['after_set']} -> {c['next_set']}: short break, wipe at {c['out_s']:.1f} s (nothing cut)")
    if not cuts:
        log("set breaks: no cuts" + ("" if SET_CUTS else " (turned off)"))
    for fl in flags:
        log("flag: " + fl)
    log("PLAN OK")
    return p


# -------------------------------------------------------------------- DRAWING
def font(sz, w="Bold"): return ImageFont.truetype(os.path.join(FONTS, f"BarlowCondensed-{w}.ttf"), int(sz))
def ease(x): x = min(max(x, 0.0), 1.0); return 1 - (1 - x) ** 3
def ramp(t, a, b): return ease((t - a) / (b - a))
def io(t, a, b): x = min(max((t - a) / (b - a), 0.0), 1.0); return 0.5 - 0.5 * math.cos(math.pi * x)
def back(x): x = min(max(x, 0.0), 1.0); c1 = 1.70158; return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


class Layer:
    def __init__(self, draw_fn):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); draw_fn(im)
        bb = im.getbbox() or (0, 0, 1, 1); self.img = im.crop(bb); self.x, self.y = bb[0], bb[1]
    def put(self, frame, alpha=1.0, dx=0, dy=0, scale=1.0, yscale=1.0, xcrop=None):
        if alpha <= 0.003: return
        im, x, y = self.img, self.x, self.y
        if xcrop is not None:                               # grow from the centre (line)
            w = im.width; a = int(w * (1 - xcrop) / 2); b = int(w * (1 + xcrop) / 2)
            if b - a < 2: return
            im = im.crop((a, 0, b, im.height)); x += a
        if scale != 1.0 or yscale != 1.0:
            w, h = im.size; nw, nh = max(1, int(w * scale)), max(1, int(h * scale * yscale))
            im = im.resize((nw, nh), Image.BICUBIC); x += (w - nw) // 2; y += (h - nh) // 2
        if alpha < 1.0:
            im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
        frame.alpha_composite(im, (int(x + dx), int(y + dy)))


def rr(box, fill, r=44, outline=(255, 255, 255, 40), width=4):
    return lambda im: ImageDraw.Draw(im).rounded_rectangle(box, r, fill=fill, outline=outline, width=width)
def tx(xy, s, f, fill=WHITE, anchor="mm", spacing=0):
    def fn(im):
        d = ImageDraw.Draw(im)
        if spacing:
            w = sum(d.textlength(c, font=f) for c in s) + spacing * (len(s) - 1)
            x = xy[0] - w / 2 if anchor[0] == "m" else xy[0]
            for c in s:
                d.text((x, xy[1]), c, font=f, fill=fill, anchor="l" + anchor[1]); x += d.textlength(c, font=f) + spacing
        else:
            d.text(xy, s, font=f, fill=fill, anchor=anchor)
    return fn
def fit(s, size, maxw, w="Bold"):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8))); f = font(size, w)
    while d.textlength(s, font=f) > maxw and f.size > 20: f = font(f.size - 2, w)
    return f
def initials(name):
    words = [w for w in re.split(r"\s+", name) if w and w[0].isalpha()]
    return (words[0][0] + words[1][0]).upper() if len(words) > 1 else name[:2].upper()
def badge(c, r, name, ring, logo_path=None):
    def fn(im):
        d = ImageDraw.Draw(im)
        # ring thickness: was a fixed 12 px; 2026-10-02 (Kenny) slightly thinner and
        # scaled to the badge size (intro ~8 px, FINAL screen 6 px)
        t = int(round(max(6, r * 0.036)))
        d.ellipse([c[0] - r - t, c[1] - r - t, c[0] + r + t, c[1] + r + t], fill=ring + (255,))
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(10, 10, 10, 255))
        if logo_path and os.path.exists(logo_path):
            # 2026-10-21 (Kenny): sized by the visible drawing (+ optical factor from
            # team-logos\logo-sizes.txt) so every logo looks the same size; centred on its ink.
            # Old: whole canvas at 1.9 r.
            lg = Image.open(logo_path).convert("RGBA")
            try:
                sys.path.insert(0, WORK)
                import logo_sizes
                W0, H0, x0, y0, x1, y1 = logo_sizes.ink_box(logo_path)
                k = r * 1.50 * logo_sizes.factor(logo_path) / max(1, y1 - y0)
                k = min(k, r * 1.62 / max(1, x1 - x0))            # never wider than the circle allows
                lg = lg.crop((x0, y0, x1, y1))
                lg = lg.resize((max(1, round(lg.width * k)), max(1, round(lg.height * k))), Image.LANCZOS)
            except Exception:
                lg = lg.resize((int(r * 1.9), int(r * 1.9)), Image.LANCZOS)
            im.alpha_composite(lg, (c[0] - lg.width // 2, c[1] - lg.height // 2))
        else:
            # centre the letters' actual ink in the circle (2026-09-28: anchor "mm" centres
            # the font's full line box, which left "TP" visibly off-centre)
            f, s = font(r * 0.95), initials(name)
            bx = d.textbbox((0, 0), s, font=f, anchor="lt")
            d.text((c[0] - (bx[0] + bx[2]) / 2, c[1] - (bx[1] + bx[3]) / 2), s, font=f, fill=ring, anchor="lt")
    return fn
_SKIP = {"THE", "TEAM", "CLUB", "VC", "VBC"}
_AWKWARD = {"TIT", "ASS", "SEX", "FAT", "POO", "PEE", "DIE", "FAG", "GAY", "NUT", "CUM", "FUK", "FUC", "WTF", "KKK", "NAZ", "PIS", "SUK"}
def team_code(name):
    """3-letter code for a team: first 3 letters of its first real word (Thundercats
    Polar -> THU); an awkward result uses the first letter + next consonants instead
    (Titans -> TTN)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name.upper()) if w and w[0].isalpha()]
    words = [w for w in words if w not in _SKIP] or words or [name.upper() or "OPP"]
    w = words[0]
    cons = "".join(ch for ch in w[1:] if ch.isalpha() and ch not in "AEIOU")
    tries = [w[:3], (w[0] + cons)[:3], (w[0] + cons[-2:])[:3],
             ("".join(x[0] for x in words) + w)[:3]]
    for c in tries:
        if len(c) == 3 and c not in _AWKWARD:
            return c
    return w[:3]


def _slug(x):
    return re.sub(r"[^a-z0-9]+", "-", (x or "").lower()).strip("-")


def logo_for(name):
    """team-logos\\<club>.png for any name that STARTS with the club's words
    ("thundercats.png" -> "Thundercats Polar 14U"); team-logos\\aliases.txt
    ("tvc = toronto-volleyball-club") for nicknames. 2026-10-02 — same rules as
    build-scoreboard.lua logoFor(). Returns a path that may not exist."""
    s = re.sub(r"^the-", "", _slug(name))
    exact = os.path.join(LOGOS, s + ".png")
    if not s:
        return exact
    try:
        for line in open(os.path.join(LOGOS, "aliases.txt"), encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                a, b = (x.strip() for x in line.split("=", 1))
                a = re.sub(r"^the-", "", _slug(a))
                f = os.path.join(LOGOS, _slug(b) + ".png")
                if a and (s == a or s.startswith(a + "-")) and os.path.exists(f):
                    return f
    except OSError:
        pass
    if os.path.exists(exact):
        return exact
    try:
        stems = [f[:-4].lower() for f in os.listdir(LOGOS) if f.lower().endswith(".png")]
    except OSError:
        stems = []
    best = max((st for st in stems if s == st or s.startswith(st + "-")), key=len, default=None)
    return os.path.join(LOGOS, best + ".png") if best else exact


# ---------------------------------------------------------------- VIDEO I/O
def frames(p, f0, n):
    """timeline frames f0 .. f0+n-1 as RGB images (last real frame repeated past the end)"""
    done, last, acc = 0, None, 0
    for path, cn in p["clips"]:
        if done >= n: break
        lo, hi = acc, acc + cn; acc = hi
        a = max(f0 + done, lo)
        if a >= hi or a < lo: continue
        m = min(hi - a, n - done)
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{(a - lo) / FPS:.6f}", "-i", path, "-frames:v", str(m),
               "-vf", "scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        for _ in range(m):
            b = pr.stdout.read(W * H * 3)
            if len(b) < W * H * 3: break
            last = Image.frombuffer("RGB", (W, H), b); done += 1
            yield last
        pr.stdout.close(); pr.wait()
    while done < n and last is not None:
        done += 1
        yield last


def encoder(path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
           "-r", f"{FPS_NUM}/{FPS_DEN}", "-i", "-",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-c:v", "prores_ks", "-profile:v", "4444",
           "-pix_fmt", "yuva444p10le", "-alpha_bits", "16", "-vendor", "apl0",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def backdrop(img, k, dim):
    """blurred + dimmed copy of the frame with alpha k (blur done at quarter size — it's blurred anyway)"""
    if k <= 0.003:
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sm = img.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(7))
    sm = ImageEnhance.Brightness(sm).enhance(dim)
    up = sm.resize((W, H), Image.BILINEAR).convert("RGBA")
    up.putalpha(int(round(255 * min(1.0, k))))
    return up


def out_bytes(fr):
    return (fr.convert("RGBa") if PREMULT else fr).tobytes()


# ------------------------------------------------------------------- INTRO
def render_intro(p):
    it = p["intro"]
    out = os.path.join(p["folder"], "intro-overlay.mov")
    if not it["enabled"]:
        if os.path.exists(out): os.remove(out)
        log("INTRO SKIPPED"); return
    t1, t2 = p["team1"].upper(), p["team2"].upper()
    date = datetime.date.fromisoformat(p["date"]).strftime("%B %d, %Y").upper().replace(" 0", " ")
    card = Layer(rr((920, 300, 2920, 1860), (0, 0, 0, 200), r=56, width=4))
    # 2026-10-02: when the opponent has a logo too, both badges sit side by side
    # (ours green on the left, theirs sky blue on the right); otherwise ours alone.
    lg2 = logo_for(p["team2"])
    if os.path.exists(lg2):
        logo = Layer(badge((1580, 650), 215, p["team1"], GREEN, logo_for(p["team1"])))
        logo2 = Layer(badge((2260, 650), 215, p["team2"], BLUE, lg2))
    else:
        logo = Layer(badge((1920, 660), 240, p["team1"], GREEN, logo_for(p["team1"])))
        logo2 = None
    name1 = Layer(tx((1920, 1060), t1, fit(t1, 240, 1800), GREEN))
    vs = Layer(tx((1920, 1224), "VS", font(92, "SemiBold"), GREY, spacing=12))
    name2 = Layer(tx((1920, 1390), t2, fit(t2, 192, 1800)))
    line = Layer(lambda im: ImageDraw.Draw(im).rounded_rectangle((1240, 1562, 2600, 1570), 4, fill=(255, 255, 255, 70)))
    dateL = Layer(tx((1920, 1680), "MATCH REPLAY  \u00b7  " + date, font(68, "SemiBold"), GREY, spacing=6))
    O = it["hold_end"]
    enc = encoder(out)
    t0 = time.time()
    i = -1
    for i, img in enumerate(frames(p, it["start_frame"], it["n_frames"])):
        u = i / FPS
        k = ramp(u, 0.0, 0.6) * (1 - io(u, O + 0.4, O + 1.6))
        fr = backdrop(img, k, 0.45)
        o = 1 - io(u, O, O + 1.2); sc = 1 - 0.025 * io(u, O, O + 1.2)
        if o > 0.003:
            rv = ramp(u, 0.8, 1.3)
            card.put(fr, alpha=min(1, rv * 1.4) * o, yscale=max(0.02, rv), scale=sc)
            pop = (u - 0.3) / 0.6
            logo.put(fr, alpha=ramp(u, 0.3, 0.6) * o, scale=((0.6 + 0.4 * back(pop)) if pop < 1 else 1.0) * sc)
            if logo2:
                pop2 = (u - 0.45) / 0.6
                if pop2 > 0:
                    logo2.put(fr, alpha=ramp(u, 0.45, 0.75) * o, scale=((0.6 + 0.4 * back(pop2)) if pop2 < 1 else 1.0) * sc)
            for L, a, b in ((name1, 1.1, 1.5), (vs, 1.3, 1.7), (name2, 1.45, 1.85)):
                q = ramp(u, a, b); L.put(fr, alpha=q * o, dy=(1 - q) * 60)
            lp = ramp(u, 1.7, 2.2)
            if lp > 0: line.put(fr, alpha=o, xcrop=lp)
            q = ramp(u, 1.9, 2.3); dateL.put(fr, alpha=q * o, dy=(1 - q) * 32)
        enc.stdin.write(out_bytes(fr))
    enc.stdin.close(); enc.wait()
    if i + 1 != it["n_frames"] or enc.returncode != 0:
        raise RuntimeError(f"intro: wrote {i + 1} of {it['n_frames']} frames (ffmpeg {enc.returncode})")
    log(f"INTRO READY ({it['n_frames']} frames in {time.time() - t0:.0f} s) — {out}")


# ----------------------------------------------------------------- SUMMARY
def render_summary(p):
    sm = p["summary"]; st = p["stats"]
    out = os.path.join(p["folder"], "summary-overlay.mov")
    t1, t2 = p["team1"].upper(), p["team2"].upper()
    date = datetime.date.fromisoformat(p["date"]).strftime("%B %d, %Y").upper().replace(" 0", " ")
    sets, (w1, w2) = st["sets"], st["won"]
    nset = len(sets)
    # 2026-10-02 (Kenny): with 3 sets "SET 1" sat right against the FINAL tab —
    # 3-set columns moved right (were 2200 + 220c, SETS 2880) and the tab narrowed
    colx = [2330 + 220 * c for c in range(nset)] if nset <= 2 else [2280 + 210 * c for c in range(nset)]
    SETSX = 2880 if nset <= 2 else 2930
    # 2026-10-04: scrimmages can have 4+ sets — narrower columns ending at the same
    # place as the 3-set layout; names get what is left
    if nset >= 4:
        step = max(150, min(210, 880 // (nset - 1)))
        colx = [2700 - step * (nset - 1 - c) for c in range(nset)]
    NUMF = 120 if nset <= 5 else 100
    NAMEW = 1040 if nset <= 2 else (900 if nset <= 3 else max(420, colx[0] - 90 - 1100))
    main = Layer(rr((660, 220, 3180, 1800), (0, 0, 0, 205), r=56))
    # FINAL tab fully opaque (2026-09-28): at 235/255 the main card's top edge
    # showed through as a faint line across "FINAL"
    tab = Layer(lambda im: (rr((1670, 140, 2170, 300), (41, 41, 41, 255), r=28)(im), tx((1920, 222), "FINAL", font(116), WHITE, spacing=12)(im)))
    hdr = Layer(lambda im: ([tx((x, 310), f"SET {c + 1}", font(52, "SemiBold"), GREY, spacing=6)(im) for c, x in enumerate(colx)],
                            tx((SETSX, 310), "SETS", font(52, "SemiBold"), GREY, spacing=6)(im)))
    rowsL, numsL, setsL = [], [], []
    for i, (name, won_n) in enumerate(((p["team1"], w1), (p["team2"], w2))):
        y = 500 + i * 300
        won = st.get("winner", 1 if w1 > w2 else (2 if w2 > w1 else 0)) == i + 1
        col = GREEN if i == 0 else WHITE
        def rowfn(im, i=i, y=y, name=name, won=won, col=col):
            rr((800, y - 120, 3040, y + 120), (41, 41, 41, 190) if won else (25, 25, 25, 170), r=32, outline=(255, 255, 255, 30))(im)
            ImageDraw.Draw(im).rounded_rectangle((800, y - 120, 820, y + 120), 6, fill=(GREEN if i == 0 else BLUE) + (255,))
            badge((960, y), 88, name, GREEN if i == 0 else BLUE, logo_for(name))(im)
            tx((1100, y), name.upper(), fit(name.upper(), 128, NAMEW), col, anchor="lm")(im)
        rowsL.append(Layer(rowfn))
        numsL.append([Layer(tx((colx[c], y), str(sc[i]), font(NUMF, "SemiBold"), WHITE if sc[i] > sc[1 - i] else DIMG))
                      for c, sc in enumerate(sets)])
        setsL.append(Layer(tx((SETSX, y), str(won_n), font(192), GREEN if won else DIMG)))
    wn = st.get("winner", 1 if w1 > w2 else (2 if w2 > w1 else 0))
    tp1, tp2 = st["total"]
    if not wn:          # 2 sets both played (1-1, equal points), time limit, or ended early
        win_txt, win_col = f"MATCH TIED {w1}{DASH}{w2}", WHITE
    elif st.get("decided_by") == "points":     # 2026-10-02: 1-1, most total points wins
        win_txt = f"{t1 if wn == 1 else t2} WIN ON POINTS {max(tp1, tp2)}{DASH}{min(tp1, tp2)}"
        win_col = GREEN if wn == 1 else WHITE
    else:
        winner = t1 if wn == 1 else t2
        win_txt, win_col = f"{winner} WIN {max(w1, w2)}{DASH}{min(w1, w2)}", (GREEN if wn == 1 else WHITE)
    winL = Layer(tx((1920, 1010), win_txt, fit(win_txt, 100, 2200), win_col, spacing=6))
    # Longest run / biggest lead: number + the team's short code in its colour
    # (2026-10-01, Kenny: "PARENTS" was too long) — same letters as the badge circles.
    # 2026-10-01 (Kenny): our team always "REBELS"; others = 3-letter code
    def code(team_no):
        name = p["team1"] if team_no == 1 else p["team2"]
        # 2026-10-02 (Kenny): opponent always "OPP" (standard stat-sheet short form)
        if name.strip().lower() == "venom rebels":
            txt = "REBELS"
        elif team_no == 2:
            txt = "OPP"
        else:
            txt = team_code(name)
        return (txt, GREEN if team_no == 1 else BLUE)
    mt = int(round(st["match_time"])); mts = f"{mt // 3600}:{mt % 3600 // 60:02d}:{mt % 60:02d}" if mt >= 3600 else f"{mt // 60}:{mt % 60:02d}"
    run_val = [(str(st["run"][1]), WHITE)] + ([code(st["run"][0])] if st["run"][1] else [])
    lead_val = [(f"+{st['lead'][1]}", WHITE)] + ([code(st["lead"][0])] if st["lead"][1] else [])
    stats = [("TOTAL POINTS", [(f"{st['total'][0]} {DASH} {st['total'][1]}", WHITE)]), ("LONGEST RUN", run_val),
             ("BIGGEST LEAD", lead_val), ("MATCH TIME", [(mts, WHITE)])]
    TILE_W, TILE_GAP = 560, 40          # tiles widened 2026-10-01 (were 500 + 60 gap)
    tile_x0 = 1920 - (4 * TILE_W + 3 * TILE_GAP) // 2
    def parts_fn(cx, cy, parts, size=112, gap=26, maxw=TILE_W - 70):
        """centred run of differently coloured words (shrinks to fit the tile)"""
        def fn(im):
            d = ImageDraw.Draw(im); f = font(size)
            ws = [d.textlength(s, font=f) for s, _ in parts]
            while sum(ws) + gap * (len(parts) - 1) > maxw and f.size > 60:
                f = font(f.size - 4); ws = [d.textlength(s, font=f) for s, _ in parts]
            x = cx - (sum(ws) + gap * (len(parts) - 1)) / 2
            for (s, col), w in zip(parts, ws):
                d.text((x, cy), s, font=f, fill=col, anchor="lm"); x += w + gap
        return fn
    statL = []
    for k, (lab, val) in enumerate(stats):
        x = tile_x0 + k * (TILE_W + TILE_GAP)
        statL.append(Layer(lambda im, x=x, lab=lab, val=val: (rr((x, 1160, x + TILE_W, 1500), (30, 30, 30, 190), r=28, outline=(255, 255, 255, 30))(im),
                                                              tx((x + TILE_W // 2, 1250), lab, font(52, "SemiBold"), GREY, spacing=6)(im),
                                                              parts_fn(x + TILE_W // 2, 1390, val)(im))))
    foot_txt = date + ("  \u00b7  " + SEASON[p["team1"]] if p["team1"] in SEASON else "")
    foot = Layer(tx((1920, 1660), foot_txt, font(64, "SemiBold"), GREY, spacing=4))
    enc = encoder(out)
    t0 = time.time()
    written = 0
    for i, img in enumerate(frames(p, sm["start_frame"], sm["n_frames"])):
        u = i / FPS
        fr = backdrop(img, ramp(u, 0.0, 0.5), 0.40)
        q = ramp(u, 0.3, 0.8); main.put(fr, alpha=q, scale=0.94 + 0.06 * q)
        q = ramp(u, 0.5, 0.9); tab.put(fr, alpha=q, dy=-(1 - q) * 80)
        hdr.put(fr, alpha=ramp(u, 1.3, 1.7))
        for r_, a in enumerate((0.8, 1.0)):
            q = ramp(u, a, a + 0.4); rowsL[r_].put(fr, alpha=q, dx=-(1 - q) * 120)
            for c, L in enumerate(numsL[r_]):
                q = ramp(u, 1.3 + c * 0.12, 1.6 + c * 0.12); L.put(fr, alpha=q, dy=(1 - q) * 28)
            q = (u - 1.6) / 0.45
            if q > 0: setsL[r_].put(fr, alpha=min(1, q * 2), scale=(0.5 + 0.5 * back(q)) if q < 1 else 1.0)
        q = ramp(u, 1.8, 2.2); winL.put(fr, alpha=q, dy=(1 - q) * 40)
        for k, L in enumerate(statL):
            q = (u - 2.1 - k * 0.15) / 0.4
            if q > 0: L.put(fr, alpha=min(1, q * 1.5), scale=(0.85 + 0.15 * back(q)) if q < 1 else 1.0)
        foot.put(fr, alpha=ramp(u, 2.9, 3.3))
        enc.stdin.write(out_bytes(fr))
        written = i + 1
    enc.stdin.close(); enc.wait()
    # 2026-09-28: never report READY for a short/empty clip (e.g. the summary
    # starting after the footage ended)
    if written != sm["n_frames"] or enc.returncode != 0:
        raise RuntimeError(f"summary: wrote {written} of {sm['n_frames']} frames (ffmpeg {enc.returncode})")
    log(f"SUMMARY READY ({sm['n_frames']} frames, {sm['hold_frames']} held, in {time.time() - t0:.0f} s) — {out}")


if __name__ == "__main__":
    a = sys.argv[1:] or ["plan"]
    if a[0] == "plan":
        plan()
    elif a[0] == "render":
        p = json.load(open(PLAN, encoding="utf-8"))
        kind = "intro" if a[1] == "intro" else "summary"
        # 2026-10-04: the HyperFrames intro / FINAL screen (hf-bookends.py) first; if it
        # can't be made for any reason, the classic one below is drawn instead.
        # BK_CLASSIC=1 in the environment skips straight to the classic one.
        done = False
        if not os.environ.get("BK_CLASSIC"):
            try:
                g = {"__name__": "hf_bookends"}
                exec(open(os.path.join(WORK, "hf-bookends.py"), encoding="utf-8").read(), g)
                done = g["render"](kind, p, log, logo_for)
            except Exception as e:
                msg = " ".join(str(e).split()).replace("FAILED", "failed").replace("ERROR", "error")[:300]
                log(f"{kind}: new HyperFrames screen not used ({msg}) \u2014 drawing the classic one instead")
        if not done:
            try:
                (render_intro if kind == "intro" else render_summary)(p)
            except Exception as e:
                log(f"*** {a[1].upper()} FAILED: {e!r}")
                raise
    else:
        print(__doc__)
