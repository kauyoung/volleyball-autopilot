"""
Camera-gap wipe (2026-10-26, Kenny): the set-break wipe panel with
"CAMERA TECHNICAL DIFFICULTY" + a second line (e.g. "3:40 OF SET 1 NOT RECORDED").
    C:\\Python314\\python.exe make-camera-wipe.py <suffix> "<line 1>" ["<line 2>"]
writes set-wipe\\wipe-in-<suffix>.mov + wipe-out-<suffix>.mov (same length as every other wipe,
so place-bookends.py can use them like a SET n wipe) and adds <suffix> to set-wipe.json "labels".
Skipped when the clips already exist with the same text (set-wipe.json "camera_text").
"""
import importlib.util, json, os, sys, time
from PIL import Image, ImageDraw, ImageFont

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
spec = importlib.util.spec_from_file_location("msw", os.path.join(W, "make-set-wipe.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def lines_layer(rows):
    im = Image.new("RGBA", (m.W, m.H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    total = sum(px for _, px in rows) * 1.18; y = m.H / 2 - total / 2
    for s, px in rows:
        f = ImageFont.truetype(m.FONT, px); sp = int(px * 0.06)
        ws = [f.getlength(c) for c in s]; tw = sum(ws) + sp * (len(s) - 1); x = (m.W - tw) / 2; yc = y + px * 0.59
        for c, w_ in zip(s, ws):
            d.text((x, yc), c, font=f, fill=m.WHITE, anchor="lm"); x += w_ + sp
        y += px * 1.18
    return im


def main(suffix, line1, line2=""):
    meta = json.load(open(m.META, encoding="utf-8"))
    text = line1 + ("\n" + line2 if line2 else "")
    have = all(os.path.exists(os.path.join(m.OUT, f"wipe-{k}-{suffix}.mov")) for k in ("in", "out"))
    if have and (meta.get("camera_text") or {}).get(suffix) == text and suffix in meta.get("labels", []):
        print(f"CAMERA WIPE READY (already made): {suffix}"); return 0
    t0 = time.time()
    rows = [(line1, 230)] + ([(line2, 120)] if line2 else [])
    lay = lines_layer(rows)
    nin = m.write(f"wipe-in-{suffix}.mov", m.wipe_in(lay)); nout = m.write(f"wipe-out-{suffix}.mov", m.wipe_out(lay))
    meta = json.load(open(m.META, encoding="utf-8"))
    if nin != meta.get("in_frames") or nout != meta.get("out_frames"):
        print(f"*** CAMERA WIPE LENGTH MISMATCH: {nin}/{nout} vs {meta.get('in_frames')}/{meta.get('out_frames')}"); return 1
    meta["labels"] = sorted(set(meta.get("labels", [])) | {suffix})
    meta.setdefault("camera_text", {})[suffix] = text
    json.dump(meta, open(m.META, "w", encoding="utf-8"), indent=1)
    print(f"CAMERA WIPE READY: {suffix} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
