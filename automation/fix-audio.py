"""
Venom Rebels — fix the match audio BEFORE the export (2026-09-27, Kenny approved).

Replaces the old after-export step (export a 22 GB "-master" file, then re-read
and re-write all 22 GB just to raise the volume). Now the camera audio alone is
evened out to YouTube loudness (-14 LUFS, true peak -1.5 dB — same loudnorm
settings as before), put back into the timeline, and the video is exported once.

Two parts:

1) On Kenny's PC, in the background, right after assemble-match.lua:
     C:\\Python314\\python.exe fix-audio.py make "<match folder>"
   Joins the audio of the DJI_ camera files in chapter order. Each file's audio
   is trimmed / padded to EXACTLY its video length (frames x 1001/60000 s), which
   is exactly where Resolve places each clip on the timeline, so the joins stay
   in sync to the sample. Writes "<match folder>\\match-audio-normalized.wav"
   (48 kHz 24-bit stereo) and fix-audio-log.txt next to this script.

2) Inside Resolve (run_script_unsafe), once the WAV exists:
     exec(open(r"C:\\Users\\YOURNAME\\scoreboard-pipeline\\fix-audio.py").read(),
          {"resolve": resolve, "__name__": "resolve_swap"})
   Unlinks the camera clips' audio from their video, removes that audio from
   A1, and lays the normalized WAV on A1 at frame 0. Checks the length matches
   the timeline to the frame. Writes the result to fix-audio-log.txt.
"""
import glob, os, re, subprocess, sys

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
LOG = os.environ.get("FIX_AUDIO_LOG") or os.path.join(WORK, "fix-audio-log.txt")   # override: tests only
OUT_DIR = os.environ.get("FIX_AUDIO_OUT")                                           # override: tests only
WAV_NAME = "match-audio-normalized.wav"
FPS_NUM, FPS_DEN = 60000, 1001   # DJI "60 fps" = 59.94


def log(msg, mode="a"):
    with open(LOG, mode, encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def camera_clips(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*"))
             if re.match(r"DJI_.*\.(mp4|mov)$", os.path.basename(f), re.I)]
    def chap(p):
        m = re.search(r"_(\d{4})_", os.path.basename(p))
        return (int(m.group(1)) if m else 0, os.path.basename(p))
    return sorted(files, key=chap)


def video_frames(f):
    import json
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames,r_frame_rate", "-of", "json", f],
                       capture_output=True, text=True)
    s = json.loads(r.stdout)["streams"][0]   # DJI files also list a stream group; take the stream
    return int(s["nb_frames"]), s["r_frame_rate"]


def make(folder, fade_end=None, fade_start=0.0):
    """fade_start (seconds): where the exported video starts (front trim, 2026-10-01) —
    the 1 s fade-in begins there."""
    """fade_end (seconds, optional): where the exported video ends (bookends trim a long
    tail after the summary) — the 3 s fade-out ends there instead of at the end of the
    footage, and it's silent after that."""
    log("fix-audio make: " + folder + (f" (fade out ending at {fade_end:.2f} s)" if fade_end else ""), "w")
    clips = camera_clips(folder)
    if not clips:
        log("ERROR: no DJI_ files in " + folder)
        return 1
    ins, parts, total = [], [], 0
    for i, f in enumerate(clips):
        n, rate = video_frames(f)
        if rate != f"{FPS_NUM}/{FPS_DEN}":
            log(f"*** {os.path.basename(f)} is {rate} fps, not 60000/1001 — timing assumption broken ***")
        dur = n * FPS_DEN / FPS_NUM
        total += n
        ins += ["-i", f]
        parts.append(f"[{i}:a:0]apad,atrim=0:{dur:.6f},asetpts=PTS-STARTPTS[a{i}]")
        log(f"  {os.path.basename(f)}: {n} frames = {dur:.6f} s")
    joined = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(clips))) \
        + f"concat=n={len(clips)}:v=0:a=1"
    # 2026-10-19 (Kenny "go"): read the camera files ONCE. The joined camera sound goes to a
    # temporary 32-bit float WAV (lossless copy of the decoded audio, ~2 GB for 90 min) and both
    # loudness passes read that instead of re-reading ~50 GB of video twice. Same result.
    import shutil, tempfile, time as _t
    need = total * FPS_DEN / FPS_NUM * 48000 * 2 * 4 * 1.3
    tmpdir = tempfile.gettempdir()
    if shutil.disk_usage(tmpdir).free < need + 5e9:
        tmpdir = OUT_DIR or folder
    jw = os.path.join(tmpdir, f"_venom-joined-audio-{os.getpid()}.wav")
    t0 = _t.time()
    r0 = subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostats"] + ins +
                        ["-filter_complex", joined + "[j]", "-map", "[j]", "-c:a", "pcm_f32le", "-rf64", "auto", jw],
                        capture_output=True, text=True)
    if r0.returncode != 0 or not os.path.exists(jw):
        log("ERROR: reading the camera audio failed\n" + r0.stderr[-800:])
        return 1
    log(f"camera audio read once in {_t.time() - t0:.0f} s -> {jw}")
    try:
        return _make_rest(folder, fade_end, fade_start, ["-i", jw], "[0:a]anull", total)
    finally:
        try:
            os.remove(jw)
        except Exception:
            pass


def _make_rest(folder, fade_end, fade_start, ins, joined, total):
    # Two passes (2026-09-27): one-pass loudnorm undershot (-16.6 instead of -14
    # on the Thundercats audio). Pass 1 measures the whole match, pass 2 uses
    # those measurements so it lands on target.
    TARGET = "I=-14:TP=-1.5:LRA=11"
    r1 = subprocess.run(["ffmpeg", "-y", "-v", "info", "-nostats"] + ins +
                        ["-filter_complex", joined + f",loudnorm={TARGET}:print_format=json[m]",
                         "-map", "[m]", "-f", "null", "-"], capture_output=True, text=True)
    import json
    try:
        m = json.loads(r1.stderr[r1.stderr.rfind("{"):r1.stderr.rfind("}") + 1])
    except Exception:
        log("ERROR: loudness measurement failed\n" + r1.stderr[-800:])
        return 1
    log(f"Measured: {m['input_i']} LUFS, true peak {m['input_tp']} dBTP, LRA {m['input_lra']}")
    second = (f"loudnorm={TARGET}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
              f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
              f":offset={m['target_offset']}:print_format=summary")
    out = os.path.join(OUT_DIR or folder, WAV_NAME)
    # Fades: 1 s fade-in at the start and a 3 s fade-out ending where the video
    # ends (Kenny, 2026-09-28; was 1 s out only). The fade-out also stops the
    # ~1 dB AAC peak spike Resolve's encoder made when the sound stopped abruptly.
    # If the camera stopped before the export end (held last frame), the fade
    # ends with the footage and the held part is silent.
    FADE_IN, FADE_OUT = 1.0, 3.0
    out_end = min(fade_end or 1e9, total * FPS_DEN / FPS_NUM)
    # Set-break cuts (2026-10-06): the sound dips to silence over DIP s before each cut,
    # stays silent while "SET n" is on the dark panel, and comes back over UP s as the
    # panel moves off (no hard audio jump at the join).
    DIP, UP, dips = 0.6, 0.9, ""
    # Set-break ambience (2026-10-14, Kenny): instead of silence under the "SET n" wipe, the set's
    # own sound carries on, ducked to AMB_GAIN (0.25 = -12 dB): it eases down over the wipe-in, the
    # break sound that follows the cut point carries on under the wipe-out, and the new set's sound
    # comes in over NEW_IN s once the panel has gone. AMBIENT = False brings back the old silent dip.
    AMBIENT = True
    AMB_GAIN, AMB_OUT, NEW_IN = 0.25, 0.5, 0.6
    RD_S, D_S = 53 * FPS_DEN / FPS_NUM, 120 * FPS_DEN / FPS_NUM   # wipe-in / wipe-out length
    try:
        _sw = json.load(open(os.path.join(WORK, "set-wipe", "set-wipe.json"),
                             encoding="utf-8"))
        RD_S = _sw.get("in_frames", 53) * FPS_DEN / FPS_NUM
        D_S = _sw.get("out_frames", 120) * FPS_DEN / FPS_NUM
    except Exception:
        pass
    try:
        HOLD = float(json.load(open(os.path.join(WORK, "set-wipe", "set-wipe.json"),
                                    encoding="utf-8")).get("hold_s", 1.6))
    except Exception:
        HOLD = 1.6
    try:
        bk = json.load(open(os.path.join(WORK, "bookends.json"), encoding="utf-8"))
        cuts = bk.get("cuts", []) if os.path.normcase(bk.get("folder", "")) == os.path.normcase(folder) else []
    except Exception:
        cuts = []
    if cuts and not AMBIENT:
        terms = []
        for c in cuts:
            A, B = c["out_s"], c["in_s"] + max(0.0, HOLD - 0.3)
            terms.append(f"if(lt(t\\,{A - DIP:.3f})\\,1\\,if(lt(t\\,{A:.3f})\\,({A:.3f}-t)/{DIP}\\,"
                         f"if(lt(t\\,{B:.3f})\\,0\\,if(lt(t\\,{B + UP:.3f})\\,(t-{B:.3f})/{UP}\\,1))))")
        dips = ",asetnsamples=n=256:p=0,volume=" + "*".join(terms) + ":eval=frame"
        log(f"set-break dips: {len(cuts)} (down {DIP} s, silent under SET n, up {UP} s)")
    fades = (f"afade=t=in:st={fade_start:.3f}:d={FADE_IN}"
             f",afade=t=out:st={max(0.0, out_end - FADE_OUT):.3f}:d={FADE_OUT}")
    if cuts and AMBIENT:
        K, terms, amb = len(cuts), [], []
        for i, c in enumerate(cuts):
            A, I = c["out_s"], c["in_s"]
            # main track: full -> AMB_GAIN over the wipe-in, (cut region, never heard), 0 under the wipe-out,
            # then the new set fades in over NEW_IN s starting when the panel is gone
            terms.append(f"if(lt(t\\,{A - RD_S:.3f})\\,1\\,if(lt(t\\,{A:.3f})\\,1-{1 - AMB_GAIN}*(t-{A - RD_S:.3f})/{RD_S:.3f}\\,"
                         f"if(lt(t\\,{I:.3f})\\,{AMB_GAIN}\\,if(lt(t\\,{I + D_S:.3f})\\,0\\,"
                         f"if(lt(t\\,{I + D_S + NEW_IN:.3f})\\,(t-{I + D_S:.3f})/{NEW_IN}\\,1)))))")
            # ambience: the sound that follows the cut point (A .. A+wipe-out), ducked, laid under the wipe-out at I
            amb.append(f"[a{i}]atrim=start={A:.3f}:end={A + D_S + AMB_OUT:.3f},asetpts=PTS-STARTPTS,"
                       f"aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,asetnsamples=n=256:p=0,"
                       f"volume=if(lt(t\\,{D_S:.3f})\\,{AMB_GAIN}\\,if(lt(t\\,{D_S + AMB_OUT:.3f})\\,{AMB_GAIN}*({D_S + AMB_OUT:.3f}-t)/{AMB_OUT}\\,0)):eval=frame[c{i}];"
                       f"anullsrc=r=48000:cl=stereo:d={I:.3f},aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000[z{i}];"
                       f"[z{i}][c{i}]concat=n=2:v=0:a=1[b{i}]")
        fc = (joined + "," + second + ",aresample=48000,asplit=" + str(K + 1) + "[m]" + "".join(f"[a{i}]" for i in range(K)) + ";"
              + f"[m]{fades},asetnsamples=n=256:p=0,volume=" + "*".join(terms) + ":eval=frame[mm];"
              + ";".join(amb) + ";[mm]" + "".join(f"[b{i}]" for i in range(K))
              + f"amix=inputs={K + 1}:duration=first:normalize=0:dropout_transition=0[out]")
        log(f"set-break ambience: {K} (down to {AMB_GAIN} over the wipe-in, break sound under the wipe-out, new set in over {NEW_IN} s)")
    else:
        fc = joined + "," + second + ",aresample=48000," + fades + dips + "[out]"
    cmd = ["ffmpeg", "-y", "-v", "info", "-nostats"] + ins + \
          ["-filter_complex", fc,
           "-map", "[out]", "-c:a", "pcm_s24le", "-ar", "48000", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    summary = r.stderr[r.stderr.find("Output Integrated"):r.stderr.find("Normalization Type")] \
        if "Output Integrated" in r.stderr else r.stderr[-1500:]
    log(summary.strip())
    e = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", out, "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    mi = re.findall(r"I:\s+(-?[\d.]+) LUFS", e); mp_ = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", e)
    if mi:
        log(f"Check (ebur128 on the WAV): {mi[-1]} LUFS, true peak {mp_[-1] if mp_ else '?'} dBTP")
    if r.returncode != 0 or not os.path.exists(out):
        log("ERROR: ffmpeg failed")
        return 1
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                       capture_output=True, text=True)
    wav_dur = float(p.stdout.strip())
    want = total * FPS_DEN / FPS_NUM
    log(f"WAV: {wav_dur:.4f} s, timeline needs {want:.4f} s ({total} frames), diff {1000 * (wav_dur - want):+.1f} ms")
    log("AUDIO READY" if abs(wav_dur - want) < 0.02 else "*** LENGTH MISMATCH ***")
    return 0


def swap(resolve):
    """Put the normalized WAV on A1 in place of the camera audio."""
    project = resolve.GetProjectManager().GetCurrentProject()
    tl = project.GetCurrentTimeline()
    mp = project.GetMediaPool()
    st = tl.GetStartFrame()
    N = tl.GetEndFrame() - st
    v1 = tl.GetItemListInTrack("video", 1)
    folder = os.path.dirname(v1[0].GetMediaPoolItem().GetClipProperty("File Path"))
    wav = os.path.join(folder, WAV_NAME)
    log("fix-audio swap: " + tl.GetName() + f" ({N} frames)")
    if not os.path.exists(wav):
        log("ERROR: " + wav + " not found — run 'fix-audio.py make' first")
        return False
    a1 = tl.GetItemListInTrack("audio", 1) or []
    if len(a1) == 1 and a1[0].GetName() == WAV_NAME:
        log("Already swapped — nothing to do.")
        return True
    # Unlink each camera clip's audio from its video, then remove only the audio.
    for item in v1:
        tl.SetClipsLinked([item] + [a for a in a1 if a.GetStart() == item.GetStart()], False)
    ok_del = tl.DeleteClips(a1, False) if a1 else True
    items = resolve.GetMediaStorage().AddItemListToMediaPool([wav])
    if not items:
        log("ERROR: couldn't import the WAV")
        return False
    res = mp.AppendToTimeline([{"mediaPoolItem": items[0], "startFrame": 0, "endFrame": N,
                                "trackIndex": 1, "recordFrame": st, "mediaType": 2}])
    a1 = tl.GetItemListInTrack("audio", 1) or []
    v1_after = tl.GetItemListInTrack("video", 1)
    good = (ok_del and len(a1) == 1 and a1[0].GetStart() == st and a1[0].GetDuration() == N
            and len(v1_after) == len(v1) and tl.GetEndFrame() - st == N)
    if a1:
        log(f"A1: {a1[0].GetName()}, start offset {a1[0].GetStart() - st}, {a1[0].GetDuration()} frames")
    log("AUDIO SWAPPED OK" if good else "*** AUDIO SWAP PROBLEM — check A1 by hand ***")
    return good


if __name__ == "resolve_swap":
    swap(resolve)  # noqa: F821  (provided by the exec() caller)
elif __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "make":
        sys.exit(make(sys.argv[2], float(sys.argv[3]) if len(sys.argv) >= 4 else None,
                      float(sys.argv[4]) if len(sys.argv) >= 5 else 0.0))
    print(__doc__)
