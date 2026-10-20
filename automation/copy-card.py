"""
Venom Rebels — copy the camera's SD card into a new match folder (2026-09-28).

Kenny plugs the DJI card in; Claude runs this on his PC in the background:

  C:\\Python314\\python.exe copy-card.py --match <scorekeeper .json>
        picks the clips that belong to THAT match: the scorekeeper (since
        2026-09-28) saves the real clock times the camera was running
        ("recordings"); a clip belongs to the match if it was recorded inside
        one of those windows (allowing a few minutes of camera-vs-phone clock
        difference). Folder: "<date> vs <Opponent>". The .json is copied in too.
        Works for tournament days with several matches on one card.

  Older match files without clock times, or no --match:
        --date YYYY-MM-DD (default: newest day on the card). If that day has
        more than one group of recordings (gaps > 20 min, e.g. two matches),
        it STOPS and lists the groups — re-run with --group N.

  --latest     use the newest scorekeeper file straight from the Google Drive
               folder synced on this PC (F:\\My Drive\\Venom Matches – Scorekeeper),
               2026-10-01 — no download through the chat. --recent lists the
               newest 8 there and exits.
  --list       show what's on the card (by day and group) and copy nothing
  --source X:\\DCIM   a specific card     --dest-root  default E:\\Venom Matches
  --name "vs X"      folder name suffix when there's no --match

  * copies each clip while hashing it (SHA-1), then re-reads the copy and
    checks the hash — a bad card read can't give a silently broken file.
    .part files are renamed only when verified; a re-run resumes.
  * never deletes anything from the card (Kenny formats it in the camera)

Progress + result go to copy-card-log.txt; the last line is "COPY OK ...",
"COPY NEEDS A CHOICE ..." or "*** COPY FAILED ...".
"""
import argparse, datetime as dt, glob, hashlib, json, os, re, shutil, string, subprocess, sys, time

# No console windows for ffmpeg/ffprobe/python helpers on Windows (2026-10-01:
# every call used to flash a black window). Applies to all subprocess calls here.
if os.name == "nt" and not getattr(subprocess.Popen, "_no_window", False):
    class _NoWindowPopen(subprocess.Popen):
        _no_window = True
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _NoWindowPopen


WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
LOG = os.path.join(WORK, "copy-card-log.txt")
CHUNK = 8 * 1024 * 1024
GAP_MIN = 20          # recordings further apart than this = a different match
CLOCK_TOL_MIN = 5     # camera clock vs phone clock allowance
DRIVE_DIR = "F:\\My Drive\\Venom Matches \u2013 Scorekeeper"   # Google Drive for desktop


def log(msg, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def find_sources():
    found = []
    for L in string.ascii_uppercase:
        if L in "ACE":
            continue
        dcim = f"{L}:\\DCIM"
        if os.path.isdir(dcim) and glob.glob(os.path.join(dcim, "**", "DJI_*.MP4"), recursive=True):
            found.append(dcim)
    return found


def duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def card_clips(src):
    """[(start datetime, end datetime, path)] for every DJI video clip, oldest first"""
    out = []
    for f in glob.glob(os.path.join(src, "**", "DJI_*.*"), recursive=True):
        if not re.search(r"\.(mp4|mov)$", f, re.I):
            continue                      # skip .LRF previews, .WAV, thumbnails
        m = re.match(r"DJI_(\d{14})", os.path.basename(f))
        if not m:
            continue
        start = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        out.append((start, start + dt.timedelta(seconds=duration(f)), f))
    return sorted(out)


def groups_of(clips):
    gs = []
    for c in clips:
        if gs and (c[0] - gs[-1][-1][1]).total_seconds() <= GAP_MIN * 60:
            gs[-1].append(c)
        else:
            gs.append([c])
    return gs


def describe(g):
    gb = sum(os.path.getsize(c[2]) for c in g) / 1e9
    return f"{g[0][0]:%Y-%m-%d %H:%M}–{g[-1][1]:%H:%M}, {len(g)} clips, {gb:.1f} GB"


def naive(iso):
    return dt.datetime.fromisoformat(iso).replace(tzinfo=None)   # camera names are local time too


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return h.hexdigest()
            h.update(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source"); ap.add_argument("--date"); ap.add_argument("--name", default="match")
    ap.add_argument("--match"); ap.add_argument("--group", type=int)
    ap.add_argument("--dest-root", default=r"E:\Venom Matches"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--latest", action="store_true"); ap.add_argument("--recent", action="store_true")
    a = ap.parse_args()
    log("copy-card " + time.strftime("%Y-%m-%d %H:%M"), "w")
    if a.latest or a.recent:
        js = sorted(glob.glob(os.path.join(DRIVE_DIR, "*.json")), key=os.path.getmtime, reverse=True)
        if not js:
            log(f"*** COPY FAILED: no scorekeeper files in {DRIVE_DIR} (is Google Drive for desktop running?)")
            return 1
        if a.recent:
            for j in js[:8]:
                log(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(j)))}  {os.path.basename(j)}")
            return 0
        a.match = js[0]
        log("match file (newest on Drive): " + os.path.basename(a.match))

    sources = [a.source] if a.source else find_sources()
    if not sources:
        log("*** COPY FAILED: no camera card found (no drive with DCIM\\...\\DJI_*.MP4) — is the card plugged in?")
        return 1
    if len(sources) > 1:
        log("*** COPY FAILED: more than one card found: " + ", ".join(sources) + " — use --source")
        return 1
    src = sources[0]
    clips = card_clips(src)
    if not clips:
        log("*** COPY FAILED: no DJI clips on the card")
        return 1
    all_groups = groups_of(clips)
    for i, g in enumerate(all_groups, 1):
        log(f"on card: group {i}: {describe(g)}")
    if a.list:
        return 0

    match = json.load(open(a.match, encoding="utf-8")) if a.match else None
    chosen, name, date = None, a.name, None
    start_off = None
    if match:
        date = match.get("date")
        name = f"vs {match.get('team2', 'Opponent')}"
        # start time in the folder name (2026-09-28): the same opponent twice in
        # one day (pool + playoff) must not share a folder
        if match.get("startedAt"):
            name = naive(match["startedAt"]).strftime("%H%M") + " " + name
        recs = [(naive(r["start"]), naive(r["end"]) if r.get("end") else None) for r in match.get("recordings") or []]
        if recs:
            tol = dt.timedelta(minutes=CLOCK_TOL_MIN)
            last_end = max((e for _, e in recs if e), default=recs[-1][0] + dt.timedelta(hours=3))
            log(f"match {match.get('team1')} vs {match.get('team2')}: camera ran "
                + ", ".join(f"{s:%H:%M}–{(e or last_end):%H:%M}" for s, e in recs))
            # 2026-09-28: first measure the camera-vs-phone clock difference (each
            # START / "camera recording again" should match a clip starting within a
            # few minutes), then take only clips that START inside the (shifted)
            # recording windows. A warm-up clip that ended just before the match no
            # longer slips in (it would have been glued onto the front of the video).
            diffs = []
            for s, _ in recs:
                near = [(c[0] - s).total_seconds() for c in clips if abs((c[0] - s).total_seconds()) <= tol.total_seconds()]
                if near:
                    diffs.append(min(near, key=abs))
            if not diffs:
                log("*** COPY FAILED: no clips on the card were recorded during this match's times — "
                    "wrong card, or the camera's clock is off by more than a few minutes (use --list / --group)")
                return 1
            off = sorted(diffs)[len(diffs) // 2]
            shift, slack = dt.timedelta(seconds=off), dt.timedelta(seconds=20)
            chosen = [c for c in clips
                      if any(s + shift - slack <= c[0] <= (e or last_end) + shift + slack for s, e in recs)]
            start_off = diffs[0]
            log(f"camera vs phone clock at the start: {off:+.0f} s")
            if abs(off) > 90:
                log("  (note: the camera's clock looks a bit off — set it in the DJI Mimo app when convenient)")
            outside = [c for c in clips if c[0].date() == chosen[0][0].date() and c not in chosen]
            if outside:
                log(f"  left out {len(outside)} other clip(s) from the same day (not during this match)")
    if chosen is None:
        day = a.date or (date if date else max(c[0] for c in clips).strftime("%Y-%m-%d"))
        date = day
        dgroups = [g for g in all_groups if g[0][0].strftime("%Y-%m-%d") == day]
        if not dgroups:
            log(f"*** COPY FAILED: nothing recorded on {day}")
            return 1
        if len(dgroups) > 1 and not a.group:
            log(f"COPY NEEDS A CHOICE: {day} has {len(dgroups)} separate groups of recordings "
                "(probably several matches) — re-run with --group N (numbering above), or use --match "
                "with a match file that has clock times")
            return 2
        if a.group:
            if not 1 <= a.group <= len(all_groups):
                log("*** COPY FAILED: no such group"); return 1
            chosen = all_groups[a.group - 1]; date = chosen[0][0].strftime("%Y-%m-%d")
        else:
            chosen = dgroups[0]

    files = [c[2] for c in chosen]
    total = sum(os.path.getsize(f) for f in files)
    # characters Windows can't use in a folder name (an opponent typed as "A/B" etc.)
    safe = re.sub(r'[<>:"/\\|?*]+', "-", f"{date} {name}".strip()).rstrip(". ")
    dest = os.path.join(a.dest_root, safe)
    os.makedirs(dest, exist_ok=True)
    if start_off is not None:
        # read by make-bookends.py: camera start vs START tap (sync warning).
        # .txt on purpose — the scripts look for the scorekeeper file as *.json
        json.dump({"start_offset_s": start_off, "match": os.path.basename(a.match)},
                  open(os.path.join(dest, "copy-info.txt"), "w", encoding="utf-8"))
    free = shutil.disk_usage(a.dest_root).free
    log(f"copying {len(files)} clips ({total / 1e9:.1f} GB) from {src} to {dest} — {free / 1e9:.0f} GB free")
    # 2026-10-08: the clip list for run-match's early picture check (it grabs one frame from the card)
    try:
        json.dump({"dest": dest, "files": files}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "copy-sources.txt"), "w", encoding="utf-8"))
    except Exception:
        pass
    if free < total * 1.05:
        log("*** COPY FAILED: not enough free space on the destination drive")
        return 1
    if a.match:
        shutil.copy2(a.match, os.path.join(dest, os.path.basename(a.match)))

    done, t0, verified = 0, time.time(), 0
    for f in files:
        fname = os.path.basename(f)
        out = os.path.join(dest, fname)
        size = os.path.getsize(f)
        if os.path.exists(out) and os.path.getsize(out) == size and os.path.exists(out + ".sha1"):
            if open(out + ".sha1").read().strip() == sha1_of(out):
                log(f"  {fname}: already copied and verified — skipped")
                done += size; verified += 1
                continue
        part = out + ".part"
        h = hashlib.sha1()
        with open(f, "rb") as fi, open(part, "wb") as fo:
            while True:
                b = fi.read(CHUNK)
                if not b:
                    break
                h.update(b); fo.write(b)
                done += len(b)
        src_hash = h.hexdigest()
        if sha1_of(part) != src_hash or os.path.getsize(part) != size:
            log(f"*** COPY FAILED: {fname} — the copy doesn't match the card (bad read?). Re-run to retry.")
            os.remove(part)
            return 1
        os.replace(part, out)
        shutil.copystat(f, out)
        open(out + ".sha1", "w").write(src_hash)
        verified += 1
        el = time.time() - t0
        log(f"  {fname}: {size / 1e9:.2f} GB copied + verified  ({done / total * 100:.0f}% · {done / 1e6 / max(el, 0.1):.0f} MB/s)")
    for s in glob.glob(os.path.join(dest, "*.sha1")):
        os.remove(s)
    log(f"COPY OK: {verified} clips, {total / 1e9:.1f} GB, every file verified — {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
