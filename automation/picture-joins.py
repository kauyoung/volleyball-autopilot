"""
Volleyball Autopilot - picture check across camera restarts (2026-11-03, the owner #3; Nov 1 Niagara: after the SD-card
restart the camera came back with another profile - wider and darker - and nobody noticed until the owner did).

    C:\\Python314\\python.exe picture-joins.py "<match folder>"

For every real camera stop (clip k+1 does not continue clip k) compares the frame 2 s before the stop with the
frame 2 s after the restart: brightness and the picture's broad layout (walls, floor, ceiling). Nov 1: normal
restarts 0.52-0.66, Niagara's wrong-mode clips 0.21-0.32 -> threshold 0.42; brightness change > 18% also flags.
(A zoom/pan suggestion was tried and was not reliable - the wide mode bends the picture - so zoom/pan are set by eye.) Writes <folder>\\picture-joins.txt:
    PICTURE: restart before <clip>: same picture (...)          or
    FLAG: picture changed after the camera restart before <clip> (wider x1.75, darker -22%) - suggested fix in
          clip-fix.suggested.txt (same format as clip-fix.txt; NOT applied - preview stills first)
plus <folder>\\picture-joins.jpg (before | after | after with the suggested fix) for the approval.
Never changes the video.
"""
import glob, json, os, re, subprocess, sys, datetime
import numpy as np
from PIL import Image
FF = r"C:\ffmpeg\bin\ffmpeg.exe"; FP = r"C:\ffmpeg\bin\ffprobe.exe"; NW = 0x08000000
SW, SH = 640, 360            # analysis size (source is 3840x2160)
ZOOMS = [round(1.0 + 0.05 * i, 2) for i in range(31)]   # 1.00 .. 2.50
SEAMLESS = 3.0
SAME = float(os.environ.get("PJ_SAME", 0.42))   # layout match at the same framing above this = unchanged (tuned on Nov 1)


def dur(f):
    r = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True, creationflags=NW)
    return float(r.stdout.strip())


def frame(f, t):
    r = subprocess.run([FF, "-v", "error", "-ss", f"{max(t, 0):.2f}", "-i", f, "-frames:v", "1", "-vf", f"scale={SW}:{SH}",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, creationflags=NW)
    a = np.frombuffer(r.stdout, np.uint8)
    return a[:SW * SH * 3].reshape(SH, SW, 3) if a.size >= SW * SH * 3 else None


def luma(rgb):
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32) / 255.0


def edges(y):
    gx = np.zeros_like(y); gy = np.zeros_like(y)
    gx[:, 1:-1] = y[:, 2:] - y[:, :-2]; gy[1:-1, :] = y[2:, :] - y[:-2, :]
    e = np.sqrt(gx * gx + gy * gy)
    return e / (e.mean() + 1e-6)


def match(big, small):
    """normalised cross-correlation of 'small' at every position inside 'big' (FFT); returns (score, x, y) of the best"""
    H, Wd = big.shape; h, w = small.shape
    t = small - small.mean(); tn = np.sqrt((t * t).sum()) + 1e-9
    F = np.fft.rfft2(big); T = np.fft.rfft2(t[::-1, ::-1], s=big.shape)
    num = np.fft.irfft2(F * T, s=big.shape)[h - 1:, w - 1:]          # valid positions
    ii = np.pad(big, ((1, 0), (1, 0))).cumsum(0).cumsum(1); ii2 = np.pad(big * big, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    def box(I):
        return I[h:, w:] - I[:-h, w:] - I[h:, :-w] + I[:-h, :-w]
    s1, s2 = box(ii), box(ii2)
    var = np.maximum(s2 - s1 * s1 / (h * w), 1e-9)
    ncc = num[:var.shape[0], :var.shape[1]] / (np.sqrt(var) * tn)
    y, x = np.unravel_index(np.argmax(ncc), ncc.shape)
    return float(ncc[y, x]), int(x), int(y)


def layout(rgb):
    """the picture's broad layout (walls, floor, ceiling) - blurred, so players and lens shape matter little"""
    from PIL import ImageFilter
    y = Image.fromarray((luma(rgb) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))
    a = np.asarray(y, np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


def analyse(A, B):
    """A = before (the right picture), B = after. Find the region of B that looks like all of A."""
    ea, eb = layout(A), layout(B)
    res = []
    for z in ZOOMS:
        w, h = int(round(SW / z)), int(round(SH / z))
        small = np.asarray(Image.fromarray(ea).resize((w, h), Image.BILINEAR), np.float32)
        sc, x, y = match(eb, small)
        res.append((sc, z, x, y, w, h))
    base = next(r for r in res if r[1] == 1.0)
    best = max(res, key=lambda r: r[0])
    return base, best


def fit_brightness(A, Bc):
    ya, yb = luma(A).ravel(), luma(Bc).ravel()
    qs = np.arange(5, 96, 5)
    qa, qb = np.percentile(ya, qs), np.percentile(yb, qs)
    ok = (qa > 0.02) & (qb > 0.02)
    if ok.sum() < 5:
        return 1.0, 1.0
    b, a = np.polyfit(np.log(qb[ok]), np.log(qa[ok]), 1)          # log out = power*log(slope) + power*log(in)
    power = float(np.clip(b, 0.4, 1.6)); slope = float(np.clip(np.exp(a / power), 0.6, 2.0))
    return round(slope, 2), round(power, 2)


def apply_fix(B, z, pan, tilt, slope, power):
    """same maths as make-tavo.py (_vf_for) at analysis size"""
    w, h = SW / z, SH / z
    cx, cy = SW / 2 - (pan / 6.0) / z, SH / 2 + (tilt / 6.0) / z
    x0, y0 = min(max(cx - w / 2, 0), SW - w), min(max(cy - h / 2, 0), SH - h)
    img = Image.fromarray(B).crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((SW, SH), Image.BICUBIC)
    a = np.asarray(img, np.float32) / 255.0
    return (np.clip(np.power(np.clip(a * slope, 0, 1), power), 0, 1) * 255).astype(np.uint8)


def main(folder):
    clips = sorted(glob.glob(os.path.join(folder, "DJI_*.MP4")))
    info = []
    for f in clips:
        m = re.search(r"DJI_(\d{14})", os.path.basename(f))
        info.append({"f": f, "cam": datetime.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").timestamp(), "dur": dur(f)})
    lines, sheet, fixes = [], [], []
    ref_k = 0                                        # the last clip known to have the right picture
    for k in range(1, len(info)):
        p, c = info[k - 1], info[k]
        if abs(c["cam"] - (p["cam"] + p["dur"])) <= SEAMLESS:
            continue                                 # chapter split, same recording
        name = os.path.basename(c["f"])
        tag = re.search(r"(_\d{4}_)", name).group(1)
        # several frames each side (the camera may be handled for a moment around a stop - Nov 1 Georgetown);
        # the best-matching pair decides
        rd = info[ref_k]["dur"]
        As = [x for x in (frame(info[ref_k]["f"], rd - t) for t in (2.0, 15.0, 45.0) if rd - t > 0) if x is not None]
        Bs = [x for x in (frame(c["f"], t) for t in (2.0, 15.0, 45.0) if t < c["dur"]) if x is not None]
        if not As or not Bs:
            lines.append(f"PICTURE: restart before {name}: could not read the frames"); continue
        best = max(((float((layout(a_) * layout(b_)).mean()), a_, b_) for a_ in As for b_ in Bs), key=lambda r: r[0])
        sc0, A, B = best                             # layout match at the same framing (1 = identical)
        la, lb = float(luma(A).mean()), float(luma(B).mean())
        dark = lb / max(la, 1e-6)
        if sc0 < SAME or dark < 0.82 or dark > 1.22:
            slope, power = fit_brightness(A, B)
            why = []
            if sc0 < SAME:
                why.append(f"framing/lens looks different (picture match {sc0:.2f}; normal restarts 0.5+)")
            if dark < 0.82 or dark > 1.22:
                why.append(f"{'darker' if dark < 1 else 'brighter'} by {abs(1 - dark) * 100:.0f}%")
            fixes.append({"clips": [tag], "zoom": 1.0, "pan": 0, "tilt": 0, "slope": slope, "power": power})
            lines.append(f"FLAG: picture changed after the camera restart before {name} - " + "; ".join(why) +
                         " - probably another camera mode/profile (Nov 1 Niagara). See picture-joins.jpg; fix with clip-fix.txt "
                         "after the owner OKs a preview (brightness hint in clip-fix.suggested.txt: slope "
                         f"{slope}, power {power}; zoom/pan must be set by eye)")
            sheet.append((name, A, B))
            continue                                 # keep the last right picture as the reference
        lines.append(f"PICTURE: restart before {name}: same picture (match {sc0:.2f}, brightness {(dark - 1) * 100:+.0f}%)")
        ref_k = k
    if not lines:
        lines.append("PICTURE: no camera restarts")
    if fixes:
        merged = {}
        for fx in fixes:                             # same fix for consecutive clips -> one entry
            key = json.dumps({k: v for k, v in fx.items() if k != "clips"}, sort_keys=True)
            merged.setdefault(key, []).extend(fx["clips"])
        out = [dict(json.loads(k), clips=v) for k, v in merged.items()]
        json.dump(out[0] if len(out) == 1 else out, open(os.path.join(folder, "clip-fix.suggested.txt"), "w", encoding="utf-8"), indent=1)
    if sheet:
        rows = []
        for name, A, B in sheet:
            rows.append(np.concatenate([A, B], axis=1))       # before | after
        Image.fromarray(np.concatenate(rows, axis=0)).save(os.path.join(folder, "picture-joins.jpg"), quality=85)
    open(os.path.join(folder, "picture-joins.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
