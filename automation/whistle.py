"""
Serve-whistle finder (2026-10-19, Kenny: time-out cuts + set restarts end 5 s before the serve whistle).

The referee's serve whistle is a long (~0.4-0.9 s), loud, pure tone around 3-4 kHz, ~3 s before
the serve; the rally-ending whistle is short and comes ~5 s before Kenny's point tap. Tested on
the Oct 18 match, set 1: serve whistle found for 38 of 43 points (misses = quick points with a
short/quiet whistle), 6-29 s before the tap (median 14 s).

serve_whistle(clips, fps, lo, hi) -> timeline seconds of the LAST serve-like whistle in [lo, hi]
(camera audio; clips = [(path, frames), ...] in timeline order), or None.
"""
import json, os, subprocess, tempfile, wave
import numpy as np

SR = 16000
N, H = 1024, 256
MIN_DUR = 0.35          # serve whistles are long blasts; rally-end whistles are short
TONAL, ABOVE_BG = 12.0, 12.0
NEAR_LOUDEST = 9.0      # dB: whistles from other courts are quieter
NW = 0x08000000 if os.name == "nt" else 0


def _audio(clips, fps, t0, t1):
    """mono 16 kHz samples of timeline seconds [t0, t1) from the camera clips"""
    out, pos = [], 0.0
    for path, frames in clips:
        dur = frames / fps
        a, b = max(t0, pos), min(t1, pos + dur)
        if b > a:
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a - pos:.3f}", "-t", f"{b - a:.3f}", "-i", path,
                                "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                               capture_output=True, creationflags=NW, timeout=120)
            x = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
            want = int(round((b - a) * SR))
            x = np.pad(x, (0, max(0, want - len(x))))[:want]
            out.append(x)
        pos += dur
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def whistles(x):
    """[(t_s, dur_s, peak_db)] tonal whistle events in samples x (t relative to x[0])"""
    nfr = (len(x) - N) // H
    if nfr <= 10:
        return []
    win = np.hanning(N).astype(np.float32)
    f = np.fft.rfftfreq(N, 1 / SR)
    band = (f >= 1800) & (f <= 5000)
    peak = np.zeros(nfr, np.float32); ton = np.zeros(nfr, np.float32)
    for s in range(0, nfr, 4096):
        idx = np.arange(s, min(nfr, s + 4096))
        fr = np.stack([x[i * H:i * H + N] for i in idx]) * win
        B = np.abs(np.fft.rfft(fr, axis=1))[:, band]
        pk = B.max(1); peak[idx] = pk; ton[idx] = pk / (np.median(B, 1) + 1e-9)
    db = 20 * np.log10(peak + 1e-9)
    bg = np.convolve(db, np.ones(400) / 400, mode="same")
    on = (ton > TONAL) & (db > bg + ABOVE_BG)
    ev, i = [], 0
    while i < nfr:
        if on[i]:
            j = i
            while j < nfr and (on[j] or (j + 3 < nfr and on[j + 1:j + 4].any())):
                j += 1
            ev.append((i * H / SR, (j - i) * H / SR, float(db[i:j].max())))
            i = j
        i += 1
    return ev


def serve_whistle(clips, fps, lo, hi, margin=10.0):
    if hi - lo < 1:
        return None
    t0 = max(0.0, lo - margin)
    x = _audio(clips, fps, t0, hi + margin)
    ev = [(t0 + t, d, db) for t, d, db in whistles(x)]
    if not ev:
        return None
    loud = max(db for _, _, db in ev)
    cand = [t for t, d, db in ev if lo <= t <= hi and d >= MIN_DUR and db >= loud - NEAR_LOUDEST]
    return round(cand[-1], 3) if cand else None


if __name__ == "__main__":       # test: python whistle.py <video> <lo> <hi>
    import sys
    p = sys.argv[1]
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                        "-of", "json", p], capture_output=True, text=True)
    n = int(json.loads(r.stdout)["streams"][0]["nb_frames"])
    print(serve_whistle([(p, n)], 60000 / 1001, float(sys.argv[2]), float(sys.argv[3])))
