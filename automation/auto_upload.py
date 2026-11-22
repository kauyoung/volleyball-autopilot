"""
Auto-upload when nothing is flagged (2026-11-22, the owner: "Yes auto upload if nothing gets flagged").

A match uploads (Unlisted, as always) WITHOUT waiting for upload-approved.txt when ALL of these hold:
  * auto-upload.txt says "on" (write "off" to go back to always asking);
  * the match has no FLAG / *** line (run-summary / tournament flags: timing, camera stops, picture changes ...);
  * its sync-check.txt has finished and every line is OK (no FLAG, no "unclear", not skipped);
  * the owner hasn't said hold: upload-hold.txt written after the run started, "all"/"hold" = every match, "2,3" = those.
The approval kit is still sent to the owner at READY (before the export), so he has the whole export to say "hold".
Anything flagged -> waits for his OK exactly as before.
"""
import os, re

W = os.path.dirname(os.path.abspath(__file__))
SWITCH = os.path.join(W, "auto-upload.txt")
HOLD = os.path.join(W, "upload-hold.txt")


def enabled():
    try:
        return open(SWITCH, encoding="utf-8").read().strip().lower().startswith("on")
    except Exception:
        return False


def held(since, n=None):
    """True when the owner said hold (for match n, or any match when n is None) after the run started"""
    try:
        if os.path.getmtime(HOLD) < since - 5:
            return False
        txt = open(HOLD, encoding="utf-8").read().strip().lower()
    except Exception:
        return False
    if re.search(r"\b(all|hold|yes|stop)\b", txt) or not re.findall(r"\d+", txt):
        return True
    return n is not None and n in {int(x) for x in re.findall(r"\d+", txt)}


def clean(folder, flags):
    """-> ("ok", "") / ("wait", why) / ("no", why)"""
    bad = [f for f in (flags or []) if f and f.strip()]
    if bad:
        return "no", f"{len(bad)} flag(s): {bad[0][:120]}"
    p = os.path.join(folder or "", "sync-check.txt")
    if not os.path.exists(p):
        return "wait", "score-timing check not finished"
    lines = [l for l in open(p, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    if not lines:
        return "wait", "score-timing check not finished"
    odd = [l for l in lines if l.startswith("FLAG") or "unclear" in l or "skipped" in l or "too few" in l]
    if odd:
        return "no", "score-timing check: " + odd[0][:120]
    return "ok", ""
