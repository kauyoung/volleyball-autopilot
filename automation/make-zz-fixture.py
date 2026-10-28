"""
Volleyball Autopilot — build the permanent test fixture (2026-10-14).

    python make-zz-fixture.py [source clip]

Makes  E:\\Volleyball Matches\\_zz-fixture-master\\  (never touched by tests themselves):
  * DJI_20261013181819_0018_D.MP4 — the first 300 s of the Oct 13 camera file,
    stream-copied (no re-encode, ~3 GB), same name so the pipeline treats it like a card clip
  * 2026-10-13-1818-home-team-vs-zz-test-team.json — a made-up 2-set mini match vs "Unity Shinobi 14u" (long name + logo)
    (5-point sets, ~4.5 min, a 2.5-min set break so the set-break cut + wipe runs too)
  * copy-info.txt — camera started 6 s before START (so the offset question fires)

zz-test.py copies this into a fresh "zz test match" folder for every test (hard link for
the clip, so no extra space). Source: the archive drive copy, unless given.
"""
import glob, json, os, subprocess, sys

ROOT = r"E:\Volleyball Matches"
MASTER = os.path.join(ROOT, "_zz-fixture-master")
FF = r"C:\ffmpeg\bin\ffmpeg.exe"
NAME = "DJI_20261013181819_0018_D.MP4"
JSON_NAME = "2026-10-13-1818-home-team-vs-unity-shinobi-14u.json"


def find_source():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for d in "JKLGHI":
        p = glob.glob(d + r":\Volleyball Matches\2026-10-13 1818 vs Lakeview Thunder 14U\\" + NAME)
        if p:
            return p[0]
    raise SystemExit("source clip not found — plug in the archive drive or pass the path")


def events():
    ev = [dict(t=0, set=1, score1=0, score2=0, sets1=0, sets2=0, serve=0)]
    s1 = s2 = 0
    # set 1: Home Team wins 5-2
    for k, who in enumerate([1, 1, 2, 1, 2, 1, 1]):
        if who == 1: s1 += 1
        else: s2 += 1
        ev.append(dict(t=12 + 8 * k, set=1, score1=s1, score2=s2,
                       sets1=1 if s1 == 5 else 0, sets2=0, serve=who))
    # set 2 starts 0-0 at t=150, first point at 215 (break long enough to be cut)
    ev.append(dict(t=150, set=2, score1=0, score2=0, sets1=1, sets2=0, serve=0))
    s1 = s2 = 0
    # set 2: ZZ wins 5-3 (win by 2 — a 5-4 'win' left a SET POINT tag on, 2026-10-14)
    for k, who in enumerate([2, 1, 2, 1, 2, 1, 2, 2]):
        if who == 1: s1 += 1
        else: s2 += 1
        ev.append(dict(t=215 + 6 * k, set=2, score1=s1, score2=s2,
                       sets1=1, sets2=1 if s2 == 5 else 0, serve=who))
    return ev   # totals: Home Team 8, ZZ 7; sets 1-1


def main():
    # 2026-10-14: team 2 = "Unity Shinobi 14u" (longest real name + an opponent logo) = layout stress test
    os.makedirs(MASTER, exist_ok=True)
    out = os.path.join(MASTER, NAME)
    if not os.path.exists(out):                  # clip already there: only the .json / copy-info are rewritten
        src = find_source()
        tmp = out + ".part.mp4"
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-t", "300",
                        "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-map_metadata", "0", tmp], check=True)
        os.replace(tmp, out)
        st = os.stat(src)
        os.utime(out, (st.st_atime, st.st_mtime))
    ev = events()
    m = {"version": 1, "team1": "Home Team", "team2": "Unity Shinobi 14u", "date": "2026-10-13",
         "format": {"code": "scrim", "sets": 0, "mode": "open", "pts": 5, "decider": 5},
         "result": {"sets1": 1, "sets2": 1, "points1": 8, "points2": 7, "winner": 1, "decidedBy": "points"},
         "forcedSets": [], "startedAt": "2026-10-13T18:18:25-04:00", "endedAt": "2026-10-13T18:22:55-04:00",
         "recordings": [{"start": "2026-10-13T18:18:25-04:00", "end": "2026-10-13T18:22:55-04:00"}],
         "events": ev}
    with open(os.path.join(MASTER, JSON_NAME), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    with open(os.path.join(MASTER, "copy-info.txt"), "w", encoding="utf-8") as f:
        json.dump({"start_offset_s": -6.0, "match": JSON_NAME}, f)
    print("FIXTURE OK:", MASTER, os.path.getsize(out) // 10**6, "MB,", len(ev), "events")


if __name__ == "__main__":
    main()
