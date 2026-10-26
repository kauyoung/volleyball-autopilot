"""
Serve-whistle finder, v2 (2026-10-22, Kenny "go"): the 2026-10-19 finder + a per-match PITCH FILTER.
match_pitch(clips, fps) learns the referee's whistle pitch once per match (mode of all long tonal
events, ~10 s for a 1.5 h match); serve_whistle(..., pitch=p) then only counts whistles within
PITCH_TOL Hz of it, so squeaks / other courts (~2 kHz) can't win the "last candidate" rule.
pitch=None -> exactly the old behaviour. Benchmarked on 1,518 hand-labelled serves (HF dataset
GYdevy/volleyball-whistles, 10 matches, +-1 s): hit 76.9 -> 83.0 %, >3 s off 10.8 -> 2.0 %
(>=40 s windows 27.9 -> 14.3 %). Oct 18 match: changed 5 picks, all 5 confirmed right on video.
Shorter whistles (0.25-0.30 s) were rejected: at Kenny's gym they grabbed rally-end whistles.
Old version: _backup-2026-10-22-whistle/whistle.py.
"""
import os, subprocess
import numpy as np

SR = 16000
N, H = 1024, 256
MIN_DUR = 0.35          # unchanged detector constant (used by match_pitch)
TONAL, ABOVE_BG = 12.0, 12.0
NEAR_LOUDEST = 9.0
PITCH_TOL = 400.0       # Hz around the referee's pitch
MIN_DUR_PITCH = 0.35    # min duration for pitch-matched whistles (0.25-0.30 grabbed rally-end whistles)
NW = 0x08000000 if os.name == "nt" else 0


def _audio(clips, fps, t0, t1):
    """mono 16 kHz samples of timeline seconds [t0, t1) from the camera clips (same as whistle.py)"""
    out, pos = [], 0.0
    for path, frames in clips:
        dur = frames / fps
        a, b = max(t0, pos), min(t1, pos + dur)
        if b > a:
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a - pos:.3f}", "-t", f"{b - a:.3f}", "-i", path,
                                "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                               capture_output=True, creationflags=NW, timeout=600)
            x = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
            want = int(round((b - a) * SR))
            x = np.pad(x, (0, max(0, want - len(x))))[:want]
            out.append(x)
        pos += dur
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def whistles(x):
    """[(t_s, dur_s, peak_db, pitch_hz)] -- same events as whistle.whistles, plus median peak frequency"""
    nfr = (len(x) - N) // H
    if nfr <= 10:
        return []
    win = np.hanning(N).astype(np.float32)
    f = np.fft.rfftfreq(N, 1 / SR)
    band = (f >= 1800) & (f <= 5000)
    fb = f[band]
    peak = np.zeros(nfr, np.float32); ton = np.zeros(nfr, np.float32); hz = np.zeros(nfr, np.float32)
    for s in range(0, nfr, 4096):
        idx = np.arange(s, min(nfr, s + 4096))
        fr = np.stack([x[i * H:i * H + N] for i in idx]) * win
        B = np.abs(np.fft.rfft(fr, axis=1))[:, band]
        pk = B.max(1); peak[idx] = pk; ton[idx] = pk / (np.median(B, 1) + 1e-9); hz[idx] = fb[B.argmax(1)]
    db = 20 * np.log10(peak + 1e-9)
    bg = np.convolve(db, np.ones(400) / 400, mode="same")
    on = (ton > TONAL) & (db > bg + ABOVE_BG)
    ev, i = [], 0
    while i < nfr:
        if on[i]:
            j = i
            while j < nfr and (on[j] or (j + 3 < nfr and on[j + 1:j + 4].any())):
                j += 1
            ev.append((i * H / SR, (j - i) * H / SR, float(db[i:j].max()), float(np.median(hz[i:j][on[i:j]]))))
            i = j
        i += 1
    return ev


def pitch_mode(ev, bin_hz=50.0):
    """referee pitch from events [(.., .., .., hz)]: mode of a 50 Hz histogram, refined by the median nearby"""
    hz = np.array([e[3] for e in ev])
    if not len(hz):
        return None
    c = np.bincount((hz // bin_hz).astype(int))
    m = (c.argmax() + 0.5) * bin_hz
    return float(np.median(hz[np.abs(hz - m) <= 100]))


def match_pitch(clips, fps, chunk=600.0):
    """per-match referee pitch: mode over all long (>= MIN_DUR) tonal events of the whole timeline"""
    total = sum(fr / fps for _, fr in clips)
    ev, t = [], 0.0
    while t < total:
        ev += [e for e in whistles(_audio(clips, fps, t, min(total, t + chunk))) if e[1] >= MIN_DUR]
        t += chunk
    return pitch_mode(ev)


def select(ev, lo, hi, pitch):
    """ev in timeline seconds; pitch=None -> old whistle.py rule"""
    if not ev:
        return None
    loud = max(e[2] for e in ev)
    if pitch is None:
        cand = [t for t, d, db, hz in ev if lo <= t <= hi and d >= MIN_DUR and db >= loud - NEAR_LOUDEST]
    else:
        cand = [t for t, d, db, hz in ev if lo <= t <= hi and db >= loud - NEAR_LOUDEST
                and abs(hz - pitch) <= PITCH_TOL and d >= MIN_DUR_PITCH]
    return round(cand[-1], 3) if cand else None


def serve_whistle(clips, fps, lo, hi, margin=10.0, pitch=None):
    if hi - lo < 1:
        return None
    t0 = max(0.0, lo - margin)
    x = _audio(clips, fps, t0, hi + margin)
    ev = [(t0 + t, d, db, hz) for t, d, db, hz in whistles(x)]
    return select(ev, lo, hi, pitch)
