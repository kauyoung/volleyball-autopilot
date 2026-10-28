"""
Volleyball Autopilot — make every team logo LOOK the same size (2026-10-21, Kenny).

Logos are sized by their visible drawing (the non-transparent part), not by the
image canvas, so empty padding in a PNG no longer makes a logo smaller. On top,
team-logos\\logo-sizes.txt can give a logo an "optical" factor (a thin line-art
logo looks smaller than a solid one at the same height), e.g.  home-team = 1.09

    python logo_sizes.py      -> writes team-logos\\_logo-ink.txt for build-scoreboard.lua
                                 (stem  W H  x0 y0 x1 y1  factor), run by prepare-match.py
make-bookends.py imports ink_box() / factor() for the intro / FINAL badges.
"""
import os, sys
from PIL import Image, ImageChops

LOGOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team-logos")


def ink_box(path):
    """(W, H, x0, y0, x1, y1) of the VISIBLE drawing; whole image if there is no alpha.
    Near-black parts (e.g. a black sticker outline) are left out: every logo sits on a
    dark bar / dark badge, where they don't show (2026-10-21, a club logo)."""
    im = Image.open(path)
    W, H = im.size
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        a = rgba.getchannel("A").point(lambda v: 255 if v > 40 else 0)
        r, g, b = rgba.convert("RGB").split()
        lit = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v > 40 else 0)
        bb = ImageChops.multiply(a, lit).getbbox() or a.getbbox()
        if bb:
            return (W, H) + bb
    return (W, H, 0, 0, W, H)


def factor(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    try:
        for line in open(os.path.join(LOGOS, "logo-sizes.txt"), encoding="utf-8"):
            line = line.split("#", 1)[0]
            if "=" in line:
                k, v = (x.strip() for x in line.split("=", 1))
                if k.lower() == stem:
                    return max(0.7, min(1.3, float(v)))
    except (OSError, ValueError):
        pass
    return 1.0


def write_table():
    rows = []
    for f in sorted(os.listdir(LOGOS)):
        if f.lower().endswith(".png"):
            p = os.path.join(LOGOS, f)
            try:
                W, H, x0, y0, x1, y1 = ink_box(p)
            except Exception:
                continue
            rows.append(f"{os.path.splitext(f)[0].lower()} {W} {H} {x0} {y0} {x1} {y1} {factor(p):.3f}")
    out = os.path.join(LOGOS, "_logo-ink.txt")
    text = "# made by logo_sizes.py — do not edit; change logo-sizes.txt instead\n" + "\n".join(rows) + "\n"
    try:
        if open(out, encoding="utf-8").read() == text:
            return len(rows)
    except OSError:
        pass
    open(out, "w", encoding="utf-8").write(text)
    return len(rows)


if __name__ == "__main__":
    print(f"logo sizes: {write_table()} logos measured")
