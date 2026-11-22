"""
Pre-flight check (2026-11-22, FIXES-TODO #16). Nov 21: Resolve was closed, then the card was missing - each found
one at a time. This checks everything up front and names ALL that is missing in one line.

    python preflight.py [--tournament] [--no-card]      -> prints, and writes preflight.txt:
        PREFLIGHT OK (warnings: ...)          or
        PREFLIGHT MISSING: <a>; <b>; ...      (+ warnings)

Checked: Resolve running, not started by the Claude app, and (tournament) freshly started (it crashed 16 min into
a 4-hour session on Nov 21 - older than 30 min = warning "restart Resolve"); a camera card (unless --no-card) and
enough space on E: for the card's newest day; the Drive scorekeeper folder; J: for the archive (warning only).
run-match.py / run-tournament.py call check() first and stop with the whole list.
"""
import glob, os, re, shutil, string, subprocess, sys, time

W = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(W, "preflight.txt")
DRIVE_DIR = "F:\\My Drive\\Volleyball Matches \u2013 Scorekeeper"
DEST = "E:\\"
NOWIN = 0x08000000


def _ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=40,
                       creationflags=NOWIN)
    return r.stdout.strip()


def resolve_info():
    """-> (running, minutes since start or None, parent process name)"""
    out = _ps("$p=Get-CimInstance Win32_Process -Filter \"Name='Resolve.exe'\" | Select -First 1;"
              "if($p){$par=(Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.ParentProcessId)\").Name;"
              "$m=[int]((Get-Date)-$p.CreationDate).TotalMinutes; \"$m|$par\"}")
    if not out:
        return False, None, ""
    m, _, par = out.partition("|")
    try:
        return True, int(m), par.strip().lower()
    except ValueError:
        return True, None, par.strip().lower()


def card():
    for L in string.ascii_uppercase:
        if L in "ACE":
            continue
        d = f"{L}:\\DCIM"
        if os.path.isdir(d):
            fs = glob.glob(os.path.join(d, "**", "DJI_*.MP4"), recursive=True)
            if fs:
                return d, fs
    return None, []


def check(tournament=False, need_card=True):
    missing, warn = [], []
    try:
        run, mins, par = resolve_info()
        if not run:
            missing.append("DaVinci Resolve is not open (open it from the Start menu)")
        elif "claude" in par:
            missing.append("Resolve was started by the Claude app - save, close and reopen it from the Start menu")
        elif tournament and mins is not None and mins > 30:
            warn.append(f"Resolve has been open {mins} min - restart it before a tournament (it crashed 16 min into a long session on Nov 21)")
    except Exception as e:
        warn.append(f"couldn't check Resolve ({e!r:.80})")
    if need_card:
        src, fs = card()
        if not src:
            missing.append("camera card not found (plug the SD card in)")
        else:
            days = {}
            for f in fs:
                m = re.match(r"DJI_(\d{8})", os.path.basename(f))
                if m:
                    days[m.group(1)] = days.get(m.group(1), 0) + os.path.getsize(f)
            need = days[max(days)] * 1.05 if days else 0
            try:
                free = shutil.disk_usage(DEST).free
                if free < need:
                    missing.append(f"not enough space on E: ({free / 1e9:.0f} GB free, the card's newest day needs {need / 1e9:.0f} GB)")
            except Exception:
                missing.append("drive E: not found")
    elif not os.path.isdir(DEST):
        missing.append("drive E: not found")
    if not os.path.isdir(DRIVE_DIR):
        missing.append("Google Drive scorekeeper folder missing on F: (start Google Drive for desktop)")
    if not os.path.isdir(r"J:\Volleyball Matches"):
        warn.append("external drive J: not plugged in (needed only for the archive at the end)")
    line = ("PREFLIGHT MISSING: " + "; ".join(missing)) if missing else "PREFLIGHT OK"
    if warn:
        line += "  (warnings: " + "; ".join(warn) + ")"
    try:
        open(OUT, "w", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass
    return missing, warn, line


if __name__ == "__main__":
    mi, wa, ln = check("--tournament" in sys.argv, "--no-card" not in sys.argv)
    print(ln)
    sys.exit(1 if mi else 0)
