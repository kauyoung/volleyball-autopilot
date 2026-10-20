"""
Venom Rebels - set-break wipe (2026-10-06, Kenny).

The intro's 14-degree panel wipe (hyperframes\venom-intro: green leading edge, blue
trailing edge, same easing), made fully opaque so the cut between two sets is hidden.
"SET n" is printed ON the panel (Kenny: no separate text animation, no green line):
the leading edge uncovers it as the panel sweeps in and the trailing edge wipes it
away as the panel leaves - text and panel move as one.
4K ProRes 4444 clips, premultiplied alpha, made once per set number:
  set-wipe\wipe-in-set<n>.mov   panel sweeps in from the left; its last frames fully cover the picture
  set-wipe\wipe-out-set<n>.mov  covered for HOLD_S, then the panel carries on off to the right
place-bookends.py puts wipe-in-set<n> on V4 ending at each set-break cut and wipe-out-set<n>
starting at the resume point, so in the cut video they play as one continuous wipe.
  C:\Python314\python.exe make-set-wipe.py [2 3 4 ...] [force]
      (default sets 2-5; existing clips are skipped unless "force")
Log: set-wipe\set-wipe-log.txt ("WIPE READY"). set-wipe.json lists what exists.
"""
import json, math, os, subprocess, sys, time
from PIL import Image, ImageChops, ImageDraw, ImageFont

WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
OUT = os.path.join(WORK, "set-wipe")
LOG = os.path.join(OUT, "set-wipe-log.txt")
META = os.path.join(OUT, "set-wipe.json")
FONT = os.path.join(WORK, "Barlow Condensed font", "BarlowCondensed-Bold.ttf")
VERSION = 3
W, H, SS = 3840, 2160, 4                    # 4x horizontal supersampling (the edges are near-vertical)
FPS = 60000 / 1001
MOVE_S = 0.8                                # sweep time each way
IN_HOLD_F = 5                               # covered frames at the end of wipe-in
HOLD_S = 1.2                                # covered time at the start of wipe-out
EDGE = 28                                   # 14 px at 1080 (intro: zoom 2)
TAN = math.tan(math.radians(14))
PANEL = (6, 9, 7, 255)                      # intro panel colour, opaque here
GREEN, BLUE = (0x70, 0xD5, 0x49, 255), (0x6B, 0xBD, 0xFF, 255)
WHITE = (242, 244, 241, 255)                # intro --paper
PANEL_W = 6144                              # 160 % of 3840, as in the intro
TEXT_PX = 460                               # "SET n" font size at 4K (230 px at 1080)
ENC = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
       "-vendor", "apl0", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
TO_OUT = "format=gbrap16le,premultiply=inplace=1,scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le"
NOWIN = 0x08000000


def bezier(x1, y1, x2, y2):
    def f(p):
        lo, hi = 0.0, 1.0
        for _ in range(40):
            t = (lo + hi) / 2
            x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
            lo, hi = (t, hi) if x < p else (lo, t)
        t = (lo + hi) / 2
        return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3
    return f


DRAWER = bezier(0.32, 0.72, 0.0, 1.0)       # motion.js venomDrawer (intro panel in)
IN_OUT = bezier(0.77, 0.0, 0.175, 1.0)      # motion.js venomInOut (intro panel out)
U_MIN, U_MAX = -TAN * H / 2, W + TAN * H / 2   # u = x + tan14 * (y - H/2) over the screen
L_IN_START = U_MIN - EDGE - 2 - PANEL_W     # panel fully off to the left
L_IN_END = U_MAX + EDGE + 2 - PANEL_W       # panel position when it first covers everything
L_OUT_START = U_MIN - EDGE - 2              # last covered position before it leaves
L_OUT_END = U_MAX + EDGE + 2                # fully off to the right


def sfx(n):
    """file suffix: set<n>, or 'timeout' for the TIME-OUT wipe (2026-10-19)"""
    return "timeout" if n == "timeout" else f"set{n}"


def title_layer(n):
    """'SET n' (or 'TIME-OUT', 2026-10-19), white, centred (letter-spacing like the intro's kicker)"""
    f = ImageFont.truetype(FONT, TEXT_PX)
    s = "TIME-OUT" if n == "timeout" else f"SET {n}"
    sp = int(TEXT_PX * 0.06)
    widths = [f.getlength(ch) for ch in s]
    tw = sum(widths) + sp * (len(s) - 1)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = (W - tw) / 2
    for ch, w_ in zip(s, widths):
        d.text((x, H / 2), ch, font=f, fill=WHITE, anchor="lm")
        x += w_ + sp
    return im


def frame(L, text):
    """panel body at u in [L, L + PANEL_W], blue stripe left of it, green stripe right of it;
    the text shows only where the panel body is"""
    im = Image.new("RGBA", (W * SS, H), (0, 0, 0, 0))
    mask = Image.new("L", (W * SS, H), 0)
    d, dm = ImageDraw.Draw(im), ImageDraw.Draw(mask)
    for u0, u1, col in ((L - EDGE, L, BLUE), (L, L + PANEL_W, PANEL), (L + PANEL_W, L + PANEL_W + EDGE, GREEN)):
        a, b = u0 + TAN * H / 2, u1 + TAN * H / 2      # x at the top row (y = 0)
        c, e = u0 - TAN * H / 2, u1 - TAN * H / 2      # x at the bottom row (y = H)
        if max(a, b, c, e) < -2 or min(a, b, c, e) > W + 2:
            continue
        poly = [(a * SS, 0), (b * SS, 0), (e * SS, H), (c * SS, H)]
        d.polygon(poly, fill=col)
        if col is PANEL:
            dm.polygon(poly, fill=255)
    out = im.convert("RGBa").resize((W, H), Image.BOX).convert("RGBA")
    m = mask.resize((W, H), Image.BOX)
    if m.getbbox():
        t = text.copy()
        t.putalpha(ImageChops.multiply(text.getchannel("A"), m))
        out.alpha_composite(t)
    return out.tobytes()


def write(name, frames):
    path = os.path.join(OUT, name)
    tmp = path[:-4] + ".tmp.mov"
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                            "-r", "60000/1001", "-i", "-", "-vf", TO_OUT] + ENC + [tmp],
                           stdin=subprocess.PIPE, creationflags=NOWIN)
    n = 0
    for fr in frames:
        enc.stdin.write(fr); n += 1
    enc.stdin.close()
    enc.wait()
    if enc.returncode:
        raise RuntimeError(f"{name}: ffmpeg {enc.returncode}")
    os.replace(tmp, path)
    return n


def wipe_in(text):
    n = int(round(MOVE_S * FPS))
    for i in range(n):
        yield frame(L_IN_START + (L_IN_END - L_IN_START) * DRAWER((i + 1) / n), text)
    full = frame(L_IN_END, text)
    for _ in range(IN_HOLD_F):
        yield full


def wipe_out(text):
    full = frame(L_OUT_START, text)
    for _ in range(int(round(HOLD_S * FPS))):
        yield full
    n = int(round(MOVE_S * FPS))
    for i in range(n):
        yield frame(L_OUT_START + (L_OUT_END - L_OUT_START) * IN_OUT(i / n), text)


def log(m, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + m + "\n")


def main(sets, force=False):
    os.makedirs(OUT, exist_ok=True)
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception:
        meta = {}
    if meta.get("version") != VERSION or meta.get("hold_s") != HOLD_S:
        meta, force = {}, True                     # older design or other timing: redraw
    have = set(meta.get("sets", [])) | set(meta.get("labels", []))
    todo = sorted((s for s in sets if force or s not in have
                   or not os.path.exists(os.path.join(OUT, f"wipe-in-{sfx(s)}.mov"))
                   or not os.path.exists(os.path.join(OUT, f"wipe-out-{sfx(s)}.mov"))), key=str)
    if not todo:
        log("WIPE READY (already made: " + ", ".join(map(str, sorted(have, key=str))) + ")", "w")
        return 0
    log("drawing the set-break wipe: sets " + ", ".join(map(str, todo)), "w")
    t0 = time.time()
    if force:
        have = set()
    for s in todo:
        text = title_layer(s)
        meta["in_frames"] = write(f"wipe-in-{sfx(s)}.mov", wipe_in(text))
        meta["out_frames"] = write(f"wipe-out-{sfx(s)}.mov", wipe_out(text))
        have.add(s)
        meta.update({"sets": sorted(x for x in have if isinstance(x, int)),
                     "labels": sorted(x for x in have if not isinstance(x, int)), "move_s": MOVE_S, "hold_s": HOLD_S, "version": VERSION,
                     "made": time.strftime("%Y-%m-%d %H:%M")})
        json.dump(meta, open(META, "w", encoding="utf-8"), indent=1)
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
