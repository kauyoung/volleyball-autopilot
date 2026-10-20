"""
Resolve freeze watchdog (2026-10-03).

Started (detached, no window) by prepare-match.py setup. Every 20 s it asks
Windows whether Resolve.exe is "Not Responding" and writes one status line to
resolve-watch.txt next to this script:

    2026-10-03 14:05:20 OK
    2026-10-03 14:07:40 FROZEN for 140 s (since 14:05:20)
    2026-10-03 14:09:00 GONE (Resolve not running)

Claude reads that file from its own sandbox, which works even when Resolve (and
the Resolve tools) are stuck — so a freeze is reported to Kenny at once instead
of after repeated timeouts. A frozen Resolve is never killed automatically.
One copy at a time (resolve-watch.pid); stops after 8 hours or when Resolve has
been closed for 15 minutes.
"""
import os, subprocess, sys, time

if os.name == "nt" and not getattr(subprocess.Popen, "_no_window", False):
    class _NoWindowPopen(subprocess.Popen):
        _no_window = True
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _NoWindowPopen

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(WORK, "resolve-watch.txt")
PID = os.path.join(WORK, "resolve-watch.pid")
FROZEN_AFTER = 45          # seconds of "Not Responding" before calling it frozen


def other_copy_running():
    try:
        pid = int(open(PID).read().strip())
    except Exception:
        return False
    if pid == os.getpid():
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return "python" in r.stdout.lower()


def status():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe", "/V", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, timeout=30)
    line = next((l for l in r.stdout.splitlines() if l.lower().startswith('"resolve.exe"')), None)
    if not line:
        return "GONE"
    return "HUNG" if "not responding" in line.lower() else "OK"


def write(msg):
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def main():
    if other_copy_running():
        return
    open(PID, "w").write(str(os.getpid()))
    t_start, hung_since, gone_since = time.time(), None, None
    while time.time() - t_start < 8 * 3600:
        try:
            s = status()
        except Exception as e:
            s = "UNKNOWN"
        now = time.time()
        if s == "HUNG":
            hung_since = hung_since or now
            gone_since = None
            secs = int(now - hung_since)
            write(f"FROZEN for {secs} s (since {time.strftime('%H:%M:%S', time.localtime(hung_since))})"
                  if secs >= FROZEN_AFTER else f"SLOW ({secs} s not responding)")
        elif s == "GONE":
            hung_since = None
            gone_since = gone_since or now
            write("GONE (Resolve not running)")
            if now - gone_since > 15 * 60:
                break
        else:
            hung_since = gone_since = None
            write(s)
        time.sleep(20)
    try:
        os.remove(PID)
    except OSError:
        pass


if __name__ == "__main__":
    main()
