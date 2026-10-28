"""
Volleyball Autopilot — copy every match folder to Kenny's external hard drive (2026-10-03).

    python archive-matches.py            # find the external drive by itself
    python archive-matches.py X:         # or name it

Copies E:\\Volleyball Matches\\<every folder> to <drive>:\\Volleyball Matches\\<same folder>,
then reads every copied file back and checks its SHA-1 against the original.
COPY ONLY — nothing is ever deleted or overwritten, on either drive:
  * a file already on the external drive with the same size + SHA-1 is skipped;
  * a file there that DIFFERS is left alone and reported (never replaced).
Files still being written (changed in the last 2 minutes) are skipped this time.

External drive = a USB disk with a drive letter, not C:/E:/F:, at least 200 GB,
and no DCIM folder (that's the camera card). Exactly one must match, otherwise
it stops with "ARCHIVE NEEDS A CHOICE" and lists the drives.

Log: archive-log.txt next to this script. Last line ARCHIVE OK / ARCHIVE FAILED.
"""
import hashlib, json, os, shutil, subprocess, sys, time

if os.name == "nt" and not getattr(subprocess.Popen, "_no_window", False):
    class _NoWindowPopen(subprocess.Popen):
        _no_window = True
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _NoWindowPopen

WORK = os.path.dirname(os.path.abspath(__file__))
SRC = r"E:\Volleyball Matches"
LOG = os.path.join(WORK, "archive-log.txt")
SKIP_DIRS = {"_tavo_tmp"}
MIN_GB = 200


def log(msg, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def usb_drives():
    ps = ("Get-Partition | Where-Object DriveLetter | ForEach-Object { $d = Get-Disk -Number $_.DiskNumber; "
          "[pscustomobject]@{L=[string]$_.DriveLetter; Bus=[string]$d.BusType; Size=[double]$_.Size; "
          "Name=[string]$d.FriendlyName} } | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout or "[]")
    return out if isinstance(out, list) else [out]


def pick_drive():
    found = []
    for d in usb_drives():
        L = (d.get("L") or "").upper()
        if not L or L in "CEF" or d.get("Bus") != "USB":
            continue
        root = L + ":\\"
        gb = (d.get("Size") or 0) / 1e9
        card = os.path.isdir(root + "DCIM")
        found.append((L, gb, card, d.get("Name", "")))
    ok = [f for f in found if f[1] >= MIN_GB and not f[2]]
    return ok, found


def sha1(path, buf=8 * 1024 * 1024):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                return h.hexdigest()
            h.update(b)


def main():
    log("archive started", "w")
    if len(sys.argv) > 1:
        dest_root = sys.argv[1].rstrip("\\/:").upper() + ":\\"
    else:
        ok, found = pick_drive()
        if len(ok) != 1:
            log("drives seen: " + (", ".join(f"{L}: {gb:.0f} GB{' (camera card)' if card else ''} {n}"
                                          for L, gb, card, n in found) or "none"))
            log("ARCHIVE NEEDS A CHOICE — " + ("no external drive found (plugged in?)" if not ok
                                               else "more than one external drive; run with the drive letter"))
            return 2
        dest_root = ok[0][0] + ":\\"
        log(f"external drive: {dest_root} ({ok[0][1]:.0f} GB, {ok[0][3]})")
    dest = os.path.join(dest_root, "Volleyball Matches")
    os.makedirs(dest, exist_ok=True)
    # an interrupted earlier run leaves "<file>.partial" (this script's own temp
    # file, never a real copy) — clear those so the file is copied again
    for base, _, files in os.walk(dest):
        for fn in files:
            if fn.endswith(".partial"):
                os.remove(os.path.join(base, fn))
                log(f"removed unfinished copy from an earlier run: {fn}")

    todo, total = [], 0
    now = time.time()
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.lower().startswith(("zz", "_zz"))]   # test folders (2026-10-14)
        for fn in files:
            s = os.path.join(base, fn)
            st = os.stat(s)
            if now - st.st_mtime < 120:
                log(f"skipped (still being written): {os.path.relpath(s, SRC)}")
                continue
            todo.append((s, os.path.join(dest, os.path.relpath(s, SRC)), st.st_size))
            total += st.st_size
    need = sum(sz for s, d, sz in todo if not os.path.exists(d))
    free = shutil.disk_usage(dest_root).free
    log(f"{len(todo)} files, {total / 1e9:.1f} GB in {SRC}; {need / 1e9:.1f} GB new; {free / 1e9:.0f} GB free on {dest_root}")
    if need > free - 2e9:
        log("ARCHIVE FAILED — not enough space on the external drive")
        return 1

    copied = same = 0
    problems = []
    t0 = time.time()
    for s, d, sz in todo:
        rel = os.path.relpath(s, SRC)
        if os.path.exists(d):
            ds = os.stat(d)
            # copied (and verified) by an earlier run: same size + same timestamp
            if ds.st_size == sz and abs(ds.st_mtime - os.stat(s).st_mtime) < 2:
                same += 1
                continue
            if ds.st_size == sz and sha1(d) == sha1(s):
                same += 1
                continue
            problems.append(f"DIFFERENT file already on the drive, left alone: {rel}")
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        tmp = d + ".partial"
        h = hashlib.sha1()
        with open(s, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                b = fi.read(8 * 1024 * 1024)
                if not b:
                    break
                h.update(b); fo.write(b)
        if sha1(tmp) != h.hexdigest():
            problems.append(f"VERIFY FAILED (copy kept as .partial): {rel}")
            continue
        os.replace(tmp, d)
        shutil.copystat(s, d)
        copied += 1
        log(f"copied + verified: {rel} ({sz / 1e9:.2f} GB)")
    for p in problems:
        log("*** " + p)
    mins = (time.time() - t0) / 60
    if problems:
        log(f"ARCHIVE FAILED — {len(problems)} problem(s); {copied} copied, {same} already there ({mins:.0f} min)")
        return 1
    log(f"ARCHIVE OK — {copied} copied, {same} already there, all verified, in {mins:.0f} min -> {dest}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"ARCHIVE FAILED — {e!r}")
        raise
