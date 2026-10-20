"""
make-picture-check.py — the early picture check (2026-10-08, Kenny: every match, because the
camera spot or ISO can change even in a familiar gym).

    PY make-picture-check.py <video clip> <out.jpg>

Grabs one frame (10 min in, or the middle of a shorter clip) and draws 4 numbered options
side by side, 2 x 2, 1280x720:
  1  As filmed
  2  Brighter                      (slope 1.06, power 0.85)
  3  Brighter + zoom 5 %           (zoom 1.05, top edge kept)
  4  Brighter + zoom 10 %          (zoom 1.10, top edge kept)
Kenny answers "1".."4" (optionally "bottom"/"centre" for the zoom anchor). run-match.py
applies it to the V1 camera clips just before the export (see OPTIONS / parse_choice there).
"""
import os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

OPTIONS = {1: ("As filmed", 1.00, 1.00, 1.00), 2: ("Brighter", 1.00, 1.06, 0.85),
           3: ("Brighter + zoom 5%", 1.05, 1.06, 0.85), 4: ("Brighter + zoom 10%", 1.10, 1.06, 0.85)}
NOWIN = 0x08000000


def grab(clip, out):
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip],
                             capture_output=True, text=True, creationflags=NOWIN).stdout or 0)
    t = min(600.0, d * 0.5) if d else 5.0
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1",
                    "-vf", "scale=1920:-2", "-q:v", "2", out], check=True, creationflags=NOWIN)
    return t


def variant(im, zoom, slope, power, anchor="top"):
    w, h = im.size
    if zoom > 1:
        cw, ch = w / zoom, h / zoom
        x0 = (w - cw) / 2
        y0 = 0 if anchor == "top" else (h - ch if anchor == "bottom" else (h - ch) / 2)
        im = im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize((w, h), Image.BICUBIC)
    if slope != 1 or power != 1:
        lut = [min(255, round(((v / 255) * slope) ** power * 255)) for v in range(256)]
        im = im.point(lut * 3)
    return im


def font(size):
    for f in ("arialbd.ttf", r"C:\Windows\Fonts\arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    return ImageFont.load_default()


def main(clip, out):
    tmp = out + ".frame.jpg"
    t = grab(clip, tmp)
    base = Image.open(tmp).convert("RGB")
    sheet = Image.new("RGB", (1280, 720), "black")
    dr = ImageDraw.Draw(sheet); f = font(22)
    for k, (n, (label, z, s, p)) in enumerate(OPTIONS.items()):
        tile = variant(base, z, s, p).resize((640, 360), Image.LANCZOS)
        x, y = (k % 2) * 640, (k // 2) * 360
        sheet.paste(tile, (x, y))
        tw = dr.textlength(f"{n}  {label}", font=f)
        dr.rectangle([x, y, x + tw + 20, y + 34], fill=(0, 0, 0))
        dr.text((x + 10, y + 5), f"{n}  {label}", fill=(112, 213, 73) if n == 1 else "white", font=f)
    dr.line([(640, 0), (640, 720)], fill="black", width=3); dr.line([(0, 360), (1280, 360)], fill="black", width=3)
    sheet.save(out, quality=82)
    try:
        os.remove(tmp)
    except Exception:
        pass
    print(f"PICTURE CHECK: {out} (frame {t:.0f} s into {os.path.basename(clip)})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
