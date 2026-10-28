"""
Volleyball Autopilot — put the intro/summary overlay clips into the match timeline (2026-09-28).

exec'd inside Resolve's scripting with `resolve` defined:
    exec(open(r"C:\\Users\\YOURNAME\\scoreboard-pipeline\\place-bookends.py", encoding="utf-8").read(),
         {"resolve": resolve, "__name__": "place_bookends"})
Reads bookends.json (make-bookends.py plan) and:
  * imports <match folder>\\intro-overlay.mov / summary-overlay.mov and lays them
    on video track 3 at their planned frames (the summary may run past the end
    of the camera footage = the held last frame),
  * re-times the scoreboard's whole-board fade (FadeAllMerge in the Scoreboard
    comp): in after the intro, out as the summary comes in,
  * writes the export range to bookends.json ("export_in"/"export_out" frames),
  * set-break cuts (2026-10-06): puts set-wipe\\wipe-in-set<n>.mov / wipe-out-set<n>.mov on video
    track 4 at each cut and builds the timeline "YouTube cut" = the Match timeline
    nested, without the set breaks ("cut_timeline", "cut_frames" in bookends.json).
    The Match timeline itself is never cut (review frames, TAVO, tweaks stay as they were).
Log: bookends-log.txt ("BOOKENDS PLACED OK").
"""
import json, os, time

WORK = r"C:\Users\YOURNAME\scoreboard-pipeline"
PLAN = os.path.join(WORK, "bookends.json")
LOG = os.path.join(WORK, "bookends-log.txt")
SB_GAP_WAIT, SB_GAP_FADE = 0.3, 1.5      # set breaks: pause after the wipe, then a slow scoreboard fade-in


def blog(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg)


def place(resolve):
    p = json.load(open(PLAN, encoding="utf-8"))
    project = resolve.GetProjectManager().GetCurrentProject()
    tl = project.GetCurrentTimeline()
    mp = project.GetMediaPool()
    st = tl.GetStartFrame()
    while tl.GetTrackCount("video") < 3:
        tl.AddTrack("video")
    existing = tl.GetItemListInTrack("video", 3) or []
    if existing:
        tl.DeleteClips(existing, False)
    ok = True
    for key, fname in (("intro", "intro-overlay.mov"), ("summary", "summary-overlay.mov")):
        seg = p[key]
        if key == "intro" and not seg.get("enabled"):
            blog("intro: none (left out)")
            continue
        path = os.path.join(p["folder"], fname)
        if not os.path.exists(path):
            blog(f"*** {fname} missing"); ok = False; continue
        old = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() == fname]
        if old:
            mp.DeleteClips(old)
        items = resolve.GetMediaStorage().AddItemListToMediaPool([path])
        if not items:
            blog(f"*** couldn't import {fname}"); ok = False; continue
        mpi = items[0]
        try:
            mpi.SetClipProperty("Alpha mode", "Premultiplied")
        except Exception:
            pass
        n = seg["n_frames"]
        mp.AppendToTimeline([{"mediaPoolItem": mpi, "startFrame": 0, "endFrame": n, "trackIndex": 3,
                              "recordFrame": st + seg["start_frame"], "mediaType": 1}])
        got = [c for c in (tl.GetItemListInTrack("video", 3) or []) if c.GetName() == fname]
        if got and got[0].GetStart() - st == seg["start_frame"] and got[0].GetDuration() == n:
            blog(f"{key}: V3 frames {seg['start_frame']}–{seg['start_frame'] + n - 1} ({n / p['fps']:.1f} s)")
        else:
            blog(f"*** {key}: placement problem"); ok = False

    # scoreboard fade in/out (Lua, inside the Scoreboard comp)
    a, b = p["intro"]["sb_in"]; c, d = p["summary"]["sb_out"]
    lg = WORK + r"\_overlay_check\fade-log.txt"
    if os.path.exists(lg):
        os.remove(lg)
    # set-break cuts (2026-10-06): board hidden while the wipe covers the join, then a slow
    # fade-in (SB_GAP_FADE s) starting SB_GAP_WAIT s after the panel has gone
    gaps = "{}"
    if p.get("cuts"):
        try:
            wm = json.load(open(os.path.join(WORK, "set-wipe", "set-wipe.json"), encoding="utf-8"))
            fps = p["fps"]
            hide_after = (wm["in_frames"] - 4) / fps        # wipe-in fully covers the screen from here
            gone = wm["out_frames"] / fps                   # wipe-out: panel fully off the screen
            gaps = "{" + ",".join("{%.3f,%.3f,%.3f}" % ((c_["out_frame"] - wm["in_frames"]) / fps + hide_after,
                                                         c_["in_s"] + gone + SB_GAP_WAIT,
                                                         c_["in_s"] + gone + SB_GAP_WAIT + SB_GAP_FADE)
                                  for c_ in p["cuts"]) + "}"
        except Exception as ex:
            blog(f"*** set-break scoreboard fades skipped: {ex}")
    resolve.Fusion().Execute(f"_G.SB_GAPS={gaps}; "
                             f"_G.SB_IN_A={a}; _G.SB_IN_B={b}; _G.SB_OUT_A={c}; _G.SB_OUT_B={d}; "
                             'dofile("C:/Users/YOURNAME/scoreboard-pipeline/set-scoreboard-fades.lua")')
    t0 = time.time()
    while not os.path.exists(lg) and time.time() - t0 < 20:
        time.sleep(0.3)
    time.sleep(0.8)
    fl = open(lg, encoding="utf-8").read().strip() if os.path.exists(lg) else "no fade log"
    blog("scoreboard fades: " + fl)
    ok = ok and fl.startswith("OK")

    p["export_in"] = st + p.get("trim_frame", 0)      # front trim (2026-10-01)
    p["export_out"] = st + p["export_end_frame"] - 1
    p.pop("cut_timeline", None); p.pop("cut_frames", None)
    if p.get("cuts"):
        ok = place_cuts(resolve, project, tl, mp, p) and ok
    json.dump(p, open(PLAN, "w", encoding="utf-8"), indent=1)
    blog("BOOKENDS PLACED OK" if ok else "*** BOOKENDS PLACEMENT PROBLEM")
    return ok


CUT_NAME = "YouTube cut"


def _find_timeline_item(folder, name):
    for c in folder.GetClipList() or []:
        if c.GetName() == name and c.GetClipProperty("Type") == "Timeline":
            return c
    for sub in folder.GetSubFolderList() or []:
        x = _find_timeline_item(sub, name)
        if x:
            return x
    return None


def place_cuts(resolve, project, tl, mp, p):
    """set-break wipes on V4 + the 'YouTube cut' timeline (2026-10-06)"""
    st = tl.GetStartFrame()
    wd = os.path.join(WORK, "set-wipe")
    try:
        wm = json.load(open(os.path.join(wd, "set-wipe.json"), encoding="utf-8"))
    except Exception:
        blog("*** set-break wipe clips missing (run make-set-wipe.py)"); return False
    while tl.GetTrackCount("video") < 4:
        tl.AddTrack("video")
    old = tl.GetItemListInTrack("video", 4) or []
    if old:
        tl.DeleteClips(old, False)
    mpis = {}
    wid = lambda c: c.get("wipe") or f"set{c['next_set']}"          # 2026-10-19: 'timeout' for time-out cuts
    for fname in sorted({f"wipe-{k}-{wid(c)}.mov" for c in p["cuts"] for k in ("in", "out")}):
        have = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() == fname]
        if have:
            mpis[fname] = have[0]; continue
        items = resolve.GetMediaStorage().AddItemListToMediaPool([os.path.join(wd, fname)])
        if not items:
            blog(f"*** couldn't import {fname}"); return False
        try:
            items[0].SetClipProperty("Alpha mode", "Premultiplied")
        except Exception:
            pass
        mpis[fname] = items[0]
    nin, nout = wm["in_frames"], wm["out_frames"]       # every wipe-out-set<n> has the same length
    ok = True
    for c in p["cuts"]:
        a, b = c["out_frame"], c["in_frame"]
        mp.AppendToTimeline([{"mediaPoolItem": mpis[f"wipe-in-{wid(c)}.mov"], "startFrame": 0, "endFrame": nin, "trackIndex": 4,
                              "recordFrame": st + a - nin, "mediaType": 1},
                             {"mediaPoolItem": mpis[f"wipe-out-{wid(c)}.mov"], "startFrame": 0, "endFrame": nout, "trackIndex": 4,
                              "recordFrame": st + b, "mediaType": 1}])
    got = sorted((x.GetStart() - st, x.GetDuration()) for x in (tl.GetItemListInTrack("video", 4) or []))
    want = sorted([(c["out_frame"] - nin, nin) for c in p["cuts"]] + [(c["in_frame"], nout) for c in p["cuts"]])
    if got != want:
        blog(f"*** set-break wipes misplaced: {got} vs {want}"); ok = False
    else:
        blog(f"set-break wipes: {len(p['cuts'])} on V4")

    # the cut timeline: Match nested, the kept stretches back to back
    mpi = _find_timeline_item(mp.GetRootFolder(), tl.GetName())
    if not mpi:
        blog("*** Match timeline not found in the media pool"); return False
    for i in range(project.GetTimelineCount(), 0, -1):
        x = project.GetTimelineByIndex(i)
        if x and x.GetName() == CUT_NAME:
            mp.DeleteTimelines([x])
    keep, pos = [], p.get("trim_frame", 0)
    for c in p["cuts"]:
        keep.append((pos, c["out_frame"])); pos = c["in_frame"]
    keep.append((pos, p["export_end_frame"]))
    ct = mp.CreateEmptyTimeline(CUT_NAME)
    if not ct:
        blog("*** couldn't create the YouTube cut timeline"); return False
    project.SetCurrentTimeline(ct)
    mp.AppendToTimeline([{"mediaPoolItem": mpi, "startFrame": s0, "endFrame": e0} for s0, e0 in keep])
    v = [(x.GetLeftOffset(), x.GetDuration()) for x in (ct.GetItemListInTrack("video", 1) or [])]
    a_ = [(x.GetLeftOffset(), x.GetDuration()) for x in (ct.GetItemListInTrack("audio", 1) or [])]
    want = [(s0, e0 - s0) for s0, e0 in keep]
    n = sum(e0 - s0 for s0, e0 in keep)
    if v != want or a_ != want or ct.GetEndFrame() - ct.GetStartFrame() != n:
        blog(f"*** YouTube cut timeline wrong: video {v}, audio {a_}, wanted {want}"); ok = False
    else:
        p["cut_timeline"], p["cut_frames"] = CUT_NAME, n
        blog(f"YouTube cut: {len(keep)} parts, {n} frames ({n / p['fps'] / 60:.1f} min; "
             f"{p.get('cut_total_s', 0) / 60:.1f} min of breaks removed)")
    project.SetCurrentTimeline(tl)          # everything else works on the Match timeline
    return ok


if __name__ == "place_bookends":
    place(resolve)  # noqa: F821
