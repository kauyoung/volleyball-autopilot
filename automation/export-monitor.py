"""
Volleyball Autopilot — export monitor (2026-10-14). Watches a Resolve export and logs, once a minute,
how fast it is going and what the PC is doing, so a slow export can be explained.

    python export-monitor.py <folder the render writes into> [<final .mp4>]

Started automatically (detached) by prepare-match.py's export phase. Passive: it never talks
to Resolve, only reads file sizes, nvidia-smi and process stats (~1 s of CPU per minute).
Stops by itself when the export is finished (final .mp4 present and nothing grew for 3 min),
when nothing has grown for 15 min, or after 8 h.

Writes next to the render, in <match folder>\\_workflow\\:
  export-monitor.csv          one row per minute
  export-monitor-summary.txt  speed per 10-minute block + what was different in the slow blocks
"""
import csv, glob, os, shutil, subprocess, sys, time

NOWIN = 0x08000000
EVERY = 60
try:
    import psutil
except Exception:
    psutil = None

SMI = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
GPU_Q = ("utilization.gpu,utilization.encoder,utilization.decoder,temperature.gpu,clocks.gr,"
         "power.draw,memory.used,clocks_throttle_reasons.active")
IGNORE = {"system idle process", "system", "idle"}


def gpu():
    try:
        r = subprocess.run([SMI, "--query-gpu=" + GPU_Q, "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, creationflags=NOWIN)
        v = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return dict(zip(["gpu%", "enc%", "dec%", "gpu_C", "gpu_MHz", "gpu_W", "vram_MB", "throttle"], v))
    except Exception:
        return {}


def written(folder, final):
    n = 0
    for f in glob.glob(os.path.join(folder, "*.mp4")):
        try: n += os.path.getsize(f)
        except OSError: pass
    if final and os.path.exists(final) and os.path.dirname(final) != folder:
        try: n += os.path.getsize(final)
        except OSError: pass
    return n


def procs(prev):
    """CPU % per process name since the last call (summed over same-name processes), top 5."""
    if not psutil:
        return {}, "", 0, 0, 0
    now = {}
    for p in psutil.process_iter(["name", "cpu_times", "memory_info"]):
        try:
            nm = (p.info["name"] or "?").lower()
            if nm in IGNORE: continue
            t = p.info["cpu_times"]
            now[p.pid] = (nm, t.user + t.system, p.info["memory_info"].rss)
        except Exception:
            pass
    usage, resolve_mb = {}, 0
    for pid, (nm, cpu, rss) in now.items():
        if nm == "resolve.exe": resolve_mb += rss / 1e6
        if pid in prev and prev[pid][0] == nm:
            usage[nm] = usage.get(nm, 0) + (cpu - prev[pid][1])
    ncpu = psutil.cpu_count() or 1
    top = sorted(((v / EVERY / ncpu * 100, k) for k, v in usage.items()), reverse=True)[:5]
    top_s = " | ".join(f"{k} {v:.0f}%" for v, k in top if v >= 1)
    return now, top_s, psutil.cpu_percent(None), psutil.virtual_memory().percent, resolve_mb


def main():
    folder = sys.argv[1]
    final = sys.argv[2] if len(sys.argv) > 2 else None
    wf = os.path.join(os.path.dirname(final) if final else folder, "_workflow")
    if not os.path.isdir(wf):
        wf = folder
    out_csv = os.path.join(wf, "export-monitor.csv")
    t0, last_bytes, last_grow = time.time(), written(folder, final), time.time()
    prev = {}
    if psutil:
        psutil.cpu_percent(None)
        prev = procs({})[0]
    rows = []
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = None
        while time.time() - t0 < 8 * 3600:
            time.sleep(EVERY)
            b = written(folder, final)
            mb_min = (b - last_bytes) / 1e6
            if b > last_bytes: last_grow = time.time()
            last_bytes = b
            prev, top, cpu, ram, rmb = procs(prev)
            row = {"time": time.strftime("%H:%M:%S"), "min": round((time.time() - t0) / 60),
                   "MB_per_min": round(mb_min), "cpu%": round(cpu), "ram%": round(ram),
                   "resolve_GB": round(rmb / 1000, 1), **gpu(), "top_processes": top}
            rows.append(row)
            if w is None:
                w = csv.DictWriter(fh, fieldnames=list(row.keys()), extrasaction="ignore")
                w.writeheader()
            w.writerow(row); fh.flush()
            idle = time.time() - last_grow
            done = final and os.path.exists(final) and idle > 180
            if done or idle > 900:
                break
    summarize(rows, os.path.join(wf, "export-monitor-summary.txt"))


def summarize(rows, path):
    while rows and float(rows[-1].get("MB_per_min") or 0) <= 0:   # drop the idle minutes after the render
        rows = rows[:-1]
    def num(r, k):
        try: return float(r.get(k) or 0)
        except ValueError: return 0.0
    blocks = [rows[i:i + 10] for i in range(0, len(rows), 10)]
    lines = [f"export monitor — {len(rows)} min logged (speed = MB written per minute; content varies, "
             "so look for big, lasting drops)", ""]
    speeds = []
    for i, bl in enumerate(blocks):
        if not bl: continue
        avg = lambda k: sum(num(r, k) for r in bl) / len(bl)
        s = avg("MB_per_min"); speeds.append(s)
        thr = sorted({r.get("throttle") for r in bl if r.get("throttle") and r.get("throttle") not in ("0x0000000000000000", "[N/A]")})
        tops = {}
        for r in bl:
            for part in (r.get("top_processes") or "").split(" | "):
                if part and not part.lower().startswith("resolve.exe"):
                    nm = part.rsplit(" ", 1)[0]; tops[nm] = tops.get(nm, 0) + 1
        busy = ", ".join(k for k, n in sorted(tops.items(), key=lambda x: -x[1])[:3] if n >= 3)
        lines.append(f"min {i*10:3d}-{i*10+len(bl):3d}: {s:6.0f} MB/min  cpu {avg('cpu%'):3.0f}%  gpu {avg('gpu%'):3.0f}%  "
                     f"enc {avg('enc%'):3.0f}%  dec {avg('dec%'):3.0f}%  gpu {avg('gpu_C'):.0f}C {avg('gpu_MHz'):.0f}MHz  "
                     f"ram {avg('ram%'):.0f}%  resolve {avg('resolve_GB'):.1f}GB"
                     + (f"  throttle {','.join(thr)}" if thr else "") + (f"  also busy: {busy}" if busy else ""))
    if rows:
        lines += ["", f"Resolve memory: {rows[0].get('resolve_GB')} GB at the start -> "
                  f"{max(float(r.get('resolve_GB') or 0) for r in rows):.1f} GB peak; PC RAM peak "
                  f"{max(float(r.get('ram%') or 0) for r in rows):.0f}%"]
    if speeds:
        best = max(speeds)
        slow = [i for i, s in enumerate(speeds) if s < 0.75 * best]
        lines += ["", f"fastest block {best:.0f} MB/min; blocks >25% slower: "
                  + (", ".join(f"min {i*10}-{i*10+10}" for i in slow) if slow else "none")]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            open(os.path.join(sys.argv[1], "export-monitor-error.txt"), "w").write(repr(e))
        except Exception:
            pass
