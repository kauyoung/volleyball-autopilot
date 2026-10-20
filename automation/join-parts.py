"""
Venom Rebels - join the YouTube export parts (set-break cuts, 2026-10-06).

When a match has set-break cuts, prepare-match.py exports each kept stretch of the
Match timeline as its own part (exporting a nested "cut" timeline was ~40 % slower).
This joins them into the final .mp4:
  video: stream copy (lossless, the parts are cut exactly at the wipe's covered frames)
  audio: each part trimmed to exactly its video length, joined, AAC 256k (keeps sync;
         the joins sit in the silent dip under the wipe)
  C:\Python314\python.exe join-parts.py <parts.json>
parts.json: {"parts": [paths...], "out": final path, "frames": expected total}
Log: join-parts-log.txt next to parts.json ("JOIN OK" / "JOIN FAILED"). The parts are
removed only after the joined file has exactly the expected frame count.
"""
import json, os, subprocess, sys, time

NW = 0x08000000


def nb_frames(path):
    """video frame count (json: DJI/Resolve files also list a stream group, which doubles csv output)"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                        "-of", "json", path], capture_output=True, text=True, creationflags=NW)
    return int(json.loads(r.stdout or "{}").get("streams", [{}])[0].get("nb_frames", 0))
FPS_NUM, FPS_DEN = 60000, 1001


def main(pj):
    log_path = os.path.join(os.path.dirname(pj), "join-parts-log.txt")
    def log(m):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + m + "\n")
    j = json.load(open(pj, encoding="utf-8"))
    parts, out, want = j["parts"], j["out"], int(j["frames"])
    if os.path.exists(out):
        log(f"JOIN FAILED: {out} already exists (never overwritten)"); return 1
    log(f"joining {len(parts)} parts -> {os.path.basename(out)}")
    t0 = time.time()
    counts = []
    for p in parts:
        counts.append(nb_frames(p))
    if sum(counts) != want:
        log(f"JOIN FAILED: parts have {counts} = {sum(counts)} frames, expected {want}"); return 1
    lst = os.path.join(os.path.dirname(pj), "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + p.replace("\\", "/").replace("'", "'\\''") + "'\n")
    ins = []
    for p in parts:
        ins += ["-i", p]
    fc = ";".join(f"[{i + 1}:a:0]atrim=0:{n * FPS_DEN / FPS_NUM:.6f},asetpts=PTS-STARTPTS[a{i}]"
                  for i, n in enumerate(counts))
    fc += ";" + "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]"
    tmp = out[:-4] + " (joining).mp4"
    cmd = (["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst] + ins +
           ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-tag:v", "hvc1",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", tmp])
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NW)
    if r.returncode:
        log("JOIN FAILED: ffmpeg " + r.stderr[-600:]); return 1
    got = nb_frames(tmp)
    if got != want:
        log(f"JOIN FAILED: joined file has {got} frames, expected {want} (parts kept)"); return 1
    os.replace(tmp, out)
    for p in parts:
        os.remove(p)
    log(f"JOIN OK: {got} frames, {os.path.getsize(out) / 1e9:.1f} GB, {time.time() - t0:.0f} s (parts removed)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1]))
    except Exception as ex:
        with open(os.path.join(os.path.dirname(sys.argv[1]), "join-parts-log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + f"JOIN FAILED: {ex}\n")
        sys.exit(1)
