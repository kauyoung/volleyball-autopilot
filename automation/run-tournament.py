"""
run-tournament.py — tournament mode (2026-10-09, Kenny approved the plan).

Several matches from one day (different gyms) in ONE run, around the normal single-match chain:

  0. free space on E: first (card footage + every export + margin). Not enough -> stops and says
     how many GB are short. Never deletes anything.
  1. picture check for every match straight from the card (one row per match, options 1-4 across)
     -> _overlay_check\\tournament\\picture-check.jpg, status "PICTURE CHECK READY"
  2. copies the card once: copy-card.py --match <file> for each of the day's scorekeeper files
     (each match's clips into its own "<date> <HHMM> vs <Opponent>" folder)
  3. event asked once (--event, or --ask-event -> event-pending.txt), used for every match
  4. setup + finish per match = run-match.py --folder <f> --hold-export --no-picture-check
     (one Resolve project per match, exactly like a single match)
  5. ONE approval kit: _overlay_check\\tournament\\approval\\ (combined review sheet = one row per match:
     review sheet + thumbnail; plus every thumbnail + YouTube text) -> "APPROVAL KIT READY"
  6. ONE picture answer (picture-pending.txt): "all 3", "3", "1:3, 2:4 bottom",
     "1:1, 2:z=1.08 s=1.04 p=0.9 a=top" (unlisted matches -> the plain answer if there is one, else as filmed)
  7. exports one after another (open project -> picture tweak -> export -> wait for EXPORT OK -> next),
     finish time per match measured on the real render speed. After the first measurement:
     "TOURNAMENT READY FOR APPROVAL". Each finished export: "match <n> EXPORT OK: <file>".
  8. TAVO files (only --tavo / --tavo 1,3) AFTER all YouTube exports (both use the graphics card)

    PY run-tournament.py [--date YYYY-MM-DD] [--event "OVA Tournament" | --ask-event] [--tavo [1,3]]
                         [--offset 5 | --offset "1:5,3:2"]
    PY run-tournament.py --folders "<folder 1>" "<folder 2>" ...     (skip the card copy: re-runs, tests)
         --offset      (2026-10-14) camera was already recording N s before START (positive = early):
                       "5" = every match, "1:5,3:2" = per match (same style as the picture answer). Written
                       into each match FOLDER's copy of the .json only (run-match.py --offset). Without it, a
                       measured gap > 3 s is announced before the copy ("OFFSET SUGGESTED" +
                       tournament-offset-suggestion.txt) and Claude asks Kenny; the answer arrives as
                       offset-pending.txt ("yes" = all suggested, "1:5, 3:2", "all 5", "no"), waited for up to
                       10 min after the copy only if Claude wrote offset-asked.txt. Never applied without --offset or an answer.
         --resume      a match whose folder already has _workflow\\ (setup + finish done) isn't set up
                       again; a match whose export file already exists isn't exported again
         --test        zz names: project + export "zz tournament <n>" (test folders only)
         --dry-run     space check + match list + picture check, nothing else
    PY run-tournament.py thumbnail <match n> <candidate n>   another thumbnail for one match

Files: tournament-status.txt (one line per step; last line = state), tournament-summary.txt (one line
per match: project, file, finish time, thumbnail, text, picture + FLAG lines), tournament-result.json,
tournament-log.txt (copy logs). Uploads stay with Claude (one at a time, after each "EXPORT OK").
Single-match days don't use this file at all.
"""
import argparse, datetime as dt, glob, importlib.util, json, os, re, shutil, subprocess, sys, time, traceback

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
PY = r"C:\Python314\python.exe"
OC = W + r"\_overlay_check"
T = OC + r"\tournament"
TSTATUS = W + r"\tournament-status.txt"
TSUMMARY = W + r"\tournament-summary.txt"
TRESULT = W + r"\tournament-result.json"
TLOG = W + r"\tournament-log.txt"
PENDING = W + r"\event-pending.txt"
PIC_PENDING = W + r"\picture-pending.txt"
PIC_ASKED = W + r"\picture-asked.txt"
ROOT = r"E:\Venom Matches"
YT_GB_H, TAVO_GB_H = 14.4, 5.5          # same as prepare-match.py
COPY_S_PER_GB = 12.5
NOWIN = 0x08000000
UTF8 = dict(os.environ, PYTHONIOENCODING="utf-8")
T_START = time.time()
R = {"matches": []}
MS = R["matches"]
sys.path.insert(0, W)
import offset_tools as ot                      # 2026-10-14: camera-start offset (see --offset)
OFF_PENDING = W + r"\offset-pending.txt"
OFF_ASKED = W + r"\offset-asked.txt"
T_OFF_SUGGEST = W + r"\tournament-offset-suggestion.txt"


class Stop(Exception):
    pass


def mod(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(W, file))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def st(msg, first=False):
    with open(TSTATUS, "w" if first else "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def tlog(msg):
    with open(TLOG, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def save():
    with open(TRESULT, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, ensure_ascii=False, default=str)


def fresh(f):
    return os.path.exists(f) and os.path.getmtime(f) >= T_START - 5


def hm(t):
    return time.strftime("%H:%M", time.localtime(t))


def iso(t):
    z = time.strftime("%z", time.localtime(t))
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + z[:3] + ":" + z[3:]


def write_summary(extra=()):
    L = list(extra)
    L.append(f"tournament: {R.get('date')} — {len(MS)} matches — event: {R.get('event') or 'none'} — "
             f"TAVO: {R.get('tavo_list') or 'off'}")
    for m in MS:
        L.append(f"match {m['n']}: {m.get('hhmm', '')} vs {m.get('team2')} | project '{m.get('project')}' | "
                 f"file '{m.get('export_file')}' | export: {m.get('export_state', 'not started')} | "
                 f"done ~{m.get('eta', '?')} (eta_iso {m.get('eta_iso')}, {m.get('eta_how', '-')}) | "
                 f"thumbnail '{m.get('thumbnail')}' | text '{m.get('text')}' | picture: {m.get('picture', '-')}"
                 + (f" | TAVO: {m['tavo_state']}" if m.get("tavo_state") else ""))
        for fl in m.get("flags", []):
            L.append(f"  match {m['n']} FLAG: {fl}")
        if m.get("offset_note"):
            L.append(f"  match {m['n']} OFFSET: {m['offset_note']}")
    if R.get("kit"):
        L.append("approval kit: " + " | ".join(R["kit"]))
    with open(TSUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def tstop(reason):
    save()
    try:
        write_summary(["TOURNAMENT STOPPED: " + reason])
    except Exception:
        pass
    st("TOURNAMENT STOPPED: " + reason)
    sys.exit(1)


def duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30, creationflags=NOWIN)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def naive(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=None)


def label(mj):
    hhmm = naive(mj["startedAt"]).strftime("%H:%M") if mj.get("startedAt") else ""
    return hhmm, mj.get("team2", "Opponent")


# ---------------------------------------------------------------- matches
def matches_from_card(a):
    cc = mod("copy_card", "copy-card.py")
    js = sorted(glob.glob(os.path.join(cc.DRIVE_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    if not js:
        tstop(f"no scorekeeper files in {cc.DRIVE_DIR} (is Google Drive for desktop running?)")
    docs = []
    for j in js[:60]:
        try:
            docs.append((j, json.load(open(j, encoding="utf-8"))))
        except Exception:
            pass
    date = a.date or docs[0][1].get("date")
    seen = {}
    for j, mj in docs:                                     # newest first: a re-saved file wins
        if mj.get("date") == date:
            seen.setdefault(mj.get("startedAt") or j, (j, mj))
    day = sorted(seen.values(), key=lambda x: x[1].get("startedAt") or "")
    if not day:
        tstop(f"no scorekeeper files for {date}")
    srcs = cc.find_sources()
    if not srcs:
        tstop("no camera card found (no drive with DCIM\\...\\DJI_*.MP4) — is the card plugged in?")
    if len(srcs) > 1:
        tstop("more than one camera card plugged in: " + ", ".join(srcs))
    clips = [c for c in cc.card_clips(srcs[0]) if c[0].strftime("%Y-%m-%d") == date]
    if not clips:
        tstop(f"nothing on the card ({srcs[0]}) was recorded on {date}")
    R.update({"date": date, "card": srcs[0], "footage_gb": sum(os.path.getsize(c[2]) for c in clips) / 1e9,
              "hours": sum((c[1] - c[0]).total_seconds() for c in clips) / 3600})
    tol = dt.timedelta(minutes=5)
    for n, (j, mj) in enumerate(day, 1):
        hhmm, t2 = label(mj)
        m = {"n": n, "json": j, "team2": t2, "hhmm": hhmm, "pic_clip": None}
        recs = mj.get("recordings") or []
        try:                                               # 2026-10-14: camera-vs-START gap, same rule as copy-card.py
            m["json_offset"] = float(mj.get("offset") or 0.0)
            if recs:
                m["gap"] = ot.gap_from_clips([naive(r["start"]) for r in recs], [c[0] for c in clips])
        except Exception:
            pass
        if recs:
            s0 = naive(recs[0]["start"])
            ends = [naive(r["end"]) for r in recs if r.get("end")]
            e = max(ends) if ends else s0 + dt.timedelta(hours=3)
            mine = [c for c in clips if s0 - tol <= c[0] <= e + tol]
            if mine:
                m["pic_clip"] = mine[0][2] if len(mine) == 1 else max(mine[:2], key=lambda c: os.path.getsize(c[2]))[2]
            m["gb"] = sum(os.path.getsize(c[2]) for c in mine) / 1e9
        MS.append(m)


def matches_from_folders(a):
    hours, gb = 0.0, 0.0
    for n, f in enumerate(a.folders, 1):
        f = f.rstrip("\\")
        if not os.path.isdir(f):
            tstop(f"match folder not found: {f}")
        js = glob.glob(f + r"\*.json")
        clips = sorted(glob.glob(f + r"\DJI_*.MP4"))
        if not js or not clips:
            tstop(f"{f} needs a scorekeeper .json and DJI_ camera files")
        j = max(js, key=os.path.getmtime)
        mj = json.load(open(j, encoding="utf-8"))
        hhmm, t2 = label(mj)
        h = sum(duration(c) for c in clips) / 3600
        hours += h
        MS.append({"n": n, "json": j, "team2": t2, "hhmm": hhmm, "folder": f, "hours": h,
                   "gap": ot.read_gap(f), "json_offset": float(mj.get("offset") or 0.0),
                   "pic_clip": clips[0] if len(clips) == 1 else max(clips[:2], key=os.path.getsize)})
        R.setdefault("date", mj.get("date"))
    R.update({"footage_gb": 0.0, "hours": hours})


def space_check(a):
    free = shutil.disk_usage(os.path.splitdrive(ROOT)[0] + "\\").free / 1e9
    tav = R.get("tavo_list") or []
    exp = R["hours"] * YT_GB_H + (R["hours"] * TAVO_GB_H * len(tav) / max(1, len(MS)))
    need = R["footage_gb"] + exp + 3 * len(MS) + 10
    R["space"] = {"free": round(free), "need": round(need), "footage": round(R["footage_gb"]), "exports": round(exp)}
    st(f"space on E: {free:.0f} GB free, this tournament needs about {need:.0f} GB "
       f"(card {R['footage_gb']:.0f} + exports ~{exp:.0f} + margin)")
    if free < need:
        tstop(f"not enough space on E: — needs ~{need:.0f} GB, {free:.0f} GB free, {need - free:.0f} GB short. "
              "Nothing was copied, nothing was deleted. Move finished matches to the external drive first.")


# ---------------------------------------------------------------- picture check (one row per match)
def picture_rows():
    for m in MS:
        if m.get("pic_img") or not m.get("pic_clip"):
            continue
        out = T + rf"\pc-{m['n']}.jpg"
        try:
            r = subprocess.run([PY, W + r"\make-picture-check.py", m["pic_clip"], out], cwd=W, env=UTF8,
                               capture_output=True, text=True, timeout=180, creationflags=NOWIN)
            if "PICTURE CHECK:" in r.stdout and os.path.exists(out):
                m["pic_img"] = out
            else:
                m["pic_error"] = (r.stdout + r.stderr)[-300:]
        except Exception as e:
            m["pic_error"] = repr(e)


def picture_combined():
    from PIL import Image, ImageDraw
    mpc = mod("mpc", "make-picture-check.py")
    rows = [m for m in MS if m.get("pic_img")]
    if len(rows) != len(MS):
        return None
    TW, TH, HB, TOP = 640, 360, 54, 60
    sheet = Image.new("RGB", (TW * 4, TOP + len(rows) * (HB + TH)), (2, 3, 3))
    d = ImageDraw.Draw(sheet)
    d.text((16, 14), "Reply one choice per match, e.g.  1:3, 2:4 bottom   — or —   all 3",
           fill="white", font=mpc.font(28))
    for k, m in enumerate(rows):
        y = TOP + k * (HB + TH)
        d.rectangle([0, y, TW * 4, y + HB - 4], fill=(30, 30, 30))
        d.text((16, y + 10), f"MATCH {m['n']}   {m.get('hhmm', '')}  vs {m['team2']}",
               fill=(112, 213, 73), font=mpc.font(30))
        im = Image.open(m["pic_img"]).convert("RGB")
        for q in range(4):                                 # 2x2 -> 4 across
            tile = im.crop(((q % 2) * TW, (q // 2) * TH, (q % 2) * TW + TW, (q // 2) * TH + TH))
            sheet.paste(tile, (q * TW, y + HB))
        for q in range(1, 4):
            d.line([(q * TW, y + HB), (q * TW, y + HB + TH)], fill=(2, 3, 3), width=4)
    sheet = sheet.resize((1920, round(sheet.height * 1920 / sheet.width)), Image.LANCZOS)
    out = T + r"\picture-check.jpg"
    sheet.save(out, quality=82)
    R["picture_check"] = out
    st("PICTURE CHECK READY: " + out)
    return out


def announce_offsets(a):
    """2026-10-14: before the copy (so it goes out with the picture check) — per match, the measured
    camera-vs-START gap and the suggested --offset. Nothing is applied here."""
    n = len(MS)
    try:
        explicit = parse_multi(a.offset, n) if a.offset else [None] * n
    except Exception:
        explicit = [None] * n
    sug = {}
    for m, ex in zip(MS, explicit):
        sg = None if ex is not None else ot.suggestion_from_gap(m.get("gap"), m.get("json_offset", 0.0))
        if sg:
            sug[m["n"]] = sg
    R["offset_suggestions"] = {str(k): v for k, v in sug.items()}
    try:
        os.remove(T_OFF_SUGGEST)
    except OSError:
        pass
    if sug:
        with open(T_OFF_SUGGEST, "w", encoding="utf-8") as f:
            json.dump(R["offset_suggestions"], f)
        st("OFFSET SUGGESTED: " + "; ".join(
            f"match {k} ({MS[k - 1]['hhmm']} vs {MS[k - 1]['team2']}): {v['text']} -> --offset {ot.fmt(v['offset'])}"
            for k, v in sug.items())
           + " — answer goes in offset-pending.txt: 'yes' (all suggested), '1:5, 3:2' (per match), 'all 5' or 'no'")
    save()


def resolve_offsets(a):
    """After the copy: decide each match's offset (--offset, or Kenny's answer). m['offset'] -> run-match --offset."""
    n = len(MS)
    ex_txt = parse_multi(a.offset, n) if a.offset else [None] * n
    explicit = []
    for x in ex_txt:
        if x is None:
            explicit.append(None)
            continue
        v, note = ot.parse_answer(x, None)
        if v is None and note != "no":
            tstop(f"--offset not understood: {a.offset!r} (use 5, or 1:5,3:2)")
        explicit.append(0.0 if v is None else v)
    sug = {int(k): v for k, v in (R.get("offset_suggestions") or {}).items()}
    answers = [None] * n
    if sug and (fresh(OFF_ASKED) or fresh(OFF_PENDING)):
        txt = None
        for i in range(41):
            if fresh(OFF_PENDING):
                txt = open(OFF_PENDING, encoding="utf-8").read()
                break
            if i == 0:
                st("waiting for the offset answer (offset-pending.txt) …")
            if i < 40:
                time.sleep(15)
        answers = parse_multi(txt, n)
        R["offset_answer"] = txt
        st("offset answer: " + (txt.strip() if txt else "none in 10 min — nothing applied"))
    for m, ex, ans in zip(MS, explicit, answers):
        sg = sug.get(m["n"])
        if a.resume and os.path.exists(os.path.join(m["folder"], "_workflow", "prepare-state.json")):
            continue                                       # already set up: the scores are placed, leave them
        if ex is not None:
            m["offset"], m["offset_note"] = ex, f"{ot.fmt(ex)} s (--offset)"
        elif sg and ans is not None:
            v, note = ot.parse_answer(ans, sg)
            if v is not None:
                m["offset"], m["offset_note"] = v, f"{ot.fmt(v)} s (Kenny: {note}; {sg['text']})"
    save()


def parse_multi(txt, n):
    """'all 3' / '3' -> every match; '1:3, 2:4 bottom' -> per match; others -> the plain part or None"""
    if not txt or not txt.strip():
        return [None] * n
    t = re.sub(r"(?i)^\s*all\b\s*[:=]?\s*", "", txt.strip())
    parts = re.split(r"(?i)(?:^|[,;\n\s])\s*(?:match\s*|m|#)?(\d+)\s*:", t)
    default = parts[0].strip(" ,;\n") or None
    per = {}
    for k in range(1, len(parts) - 1, 2):
        per[int(parts[k])] = parts[k + 1].strip(" ,;\n")
    return [per.get(i, default) for i in range(1, n + 1)]


# ---------------------------------------------------------------- per match: kit, frames
def out_dir(m):
    return os.environ.get("PREP_OUT") or m["folder"]


def collect_kit(m, rm=None):
    snap = os.path.join(m["folder"], "_workflow")
    info = json.load(open(os.path.join(snap, "youtube-info.json"), encoding="utf-8"))
    stt = json.load(open(os.path.join(snap, "prepare-state.json"), encoding="utf-8"))
    bj = json.load(open(os.path.join(snap, "bookends.json"), encoding="utf-8"))
    base = f'{info["date"]} {info["team1"]} vs {info["team2"]}'
    od = out_dir(m)
    m.update({"project": stt["project"], "base": base,
              "sheet": os.path.join(od, base + " - review sheet.jpg"),
              "thumbnail": os.path.join(od, base + " - thumbnail.jpg"),
              "text": os.path.join(od, base + " - YouTube text.txt")})
    m.setdefault("flags", bj.get("flags", []))
    name = m.get("export_name") or f'{info.get("date", stt["date"])} {stt["team1"]} vs {stt["team2"]} - YouTube'
    m["export_file"] = os.path.join(m["folder"], name + ".mp4")
    cuts = bj.get("cuts") or []
    m["frames"] = (bj["export_out"] - bj["export_in"] + 1) - sum(c["in_frame"] - c["out_frame"] for c in cuts)
    m["fps"] = bj.get("fps", 59.94)
    m["parts"] = bool(cuts)
    md = T + rf"\m{m['n']}"
    os.makedirs(md, exist_ok=True)
    if os.path.exists(m["sheet"]):
        from PIL import Image
        im = Image.open(m["sheet"]).convert("RGB")
        w = int(im.width * 0.35)
        im.resize((w, round(im.height * w / im.width)), Image.LANCZOS).save(md + r"\review-sheet-small.jpg", quality=85)
        m["sheet_small"] = md + r"\review-sheet-small.jpg"


def prepare_one(a, m):
    args = [PY, W + r"\run-match.py", "--folder", m["folder"], "--hold-export", "--no-picture-check"]
    if R.get("event"):
        args += ["--event", R["event"]]
    if m.get("offset") is not None:
        args += ["--offset", ot.fmt(m["offset"])]
    if a.test:
        args += ["--project", f"zz tournament {m['n']}", "--export-name", f"zz tournament {m['n']}"]
    st(f"match {m['n']} of {len(MS)}: setup + finish ({m['hhmm']} vs {m['team2']}) …")
    t0 = time.time()
    subprocess.run(args, cwd=W, env=UTF8, creationflags=NOWIN)
    lines = open(W + r"\run-match-status.txt", encoding="utf-8").read().strip().splitlines()
    tlog(f"--- match {m['n']} run-match-status ---\n" + "\n".join(lines))
    if not lines or "RUN READY FOR PICTURE CHECK" not in lines[-1]:
        tstop(f"match {m['n']} ({m['team2']}): " + (lines[-1][9:] if lines else "run-match gave no status")
              + f" — rerun: run-tournament.py --folders … --resume")
    try:
        summ = open(W + r"\run-summary.txt", encoding="utf-8").read().splitlines()
        m["flags"] = [l.split("FLAG: ", 1)[1] for l in summ if l.startswith("FLAG: ")] + \
                     [l for l in summ if "***" in l and "Scroll up" not in l]
    except Exception:
        pass
    collect_kit(m)
    # thumbnail choices of THIS match (the next setup clears the shared folder) -> for a re-pick later
    cand = OC + r"\thumb-candidates"
    dst = T + rf"\m{m['n']}\thumb-candidates"
    if os.path.isdir(cand):
        shutil.copytree(cand, dst, dirs_exist_ok=True)
        cs = OC + r"\approval-small\contact-small.jpg"
        if os.path.exists(cs):
            shutil.copy2(cs, T + rf"\m{m['n']}\contact-small.jpg")
    m["prep_min"] = round((time.time() - t0) / 60, 1)
    st(f"match {m['n']} ready ({m['prep_min']} min): {m['project']}")
    save()


def approval_kit():
    from PIL import Image, ImageDraw
    mpc = mod("mpc", "make-picture-check.py")
    appr = T + r"\approval"
    os.makedirs(appr, exist_ok=True)
    SW, TWID, PAD, HB = 1200, 600, 20, 64
    rows = []
    for m in MS:
        sh = Image.open(m["sheet_small"]).convert("RGB") if m.get("sheet_small") else Image.new("RGB", (SW, 400), "gray")
        sh = sh.resize((SW, round(sh.height * SW / sh.width)), Image.LANCZOS)
        th = Image.open(m["thumbnail"]).convert("RGB") if os.path.exists(m["thumbnail"]) else Image.new("RGB", (1280, 720), "gray")
        th = th.resize((TWID, round(th.height * TWID / th.width)), Image.LANCZOS)
        rows.append((m, sh, th))
    W2 = SW + TWID + 3 * PAD
    H2 = sum(HB + max(sh.height, th.height) + PAD for _, sh, th in rows)
    img = Image.new("RGB", (W2, H2), (2, 3, 3))
    d = ImageDraw.Draw(img)
    y = 0
    for m, sh, th in rows:
        d.rectangle([0, y, W2, y + HB - 6], fill=(30, 30, 30))
        fl = f"   ·   {len(m.get('flags', []))} flag(s)" if m.get("flags") else ""
        d.text((PAD, y + 14), f"MATCH {m['n']}   {m.get('hhmm', '')}  vs {m['team2']}{fl}",
               fill=(112, 213, 73), font=mpc.font(32))
        img.paste(sh, (PAD, y + HB))
        img.paste(th, (SW + 2 * PAD, y + HB))
        y += HB + max(sh.height, th.height) + PAD
    comb = appr + r"\tournament review sheet.jpg"
    img.save(comb, quality=85)
    kit = [comb]
    for m in MS:
        for k in ("thumbnail", "text"):
            if m.get(k) and os.path.exists(m[k]):
                shutil.copy2(m[k], appr)
                kit.append(appr + "\\" + os.path.basename(m[k]))
    R["kit"] = kit
    save()
    write_summary()
    st("APPROVAL KIT READY: " + comb)


# ---------------------------------------------------------------- exports, one after another
def project_etas(t, spf):
    """finish times for the exports still to come: one after another, from the (measured) speed"""
    for m in MS:
        if m.get("export_state") in ("EXPORT OK", "already there", "FAILED"):
            continue
        if m.get("export_state") == "rendering":
            t = max(t, m.get("eta_end", t))
            continue
        t += 60                                           # switch project + picture tweak
        end = t + m["frames"] * spf
        eta = end + 120 + (180 if m["parts"] else 0)      # same margins as export_status
        m.update({"eta": hm(eta), "eta_iso": iso(eta), "eta_how": "estimate", "eta_end": end})
        t = end


def export_all(a, picks):
    rm = mod("run_match", "run-match.py")
    rm.STATUS = TSTATUS
    rm.RESULT = W + r"\tournament-phases.json"

    def _stop(reason):
        raise Stop(reason)
    rm.stop = _stop
    try:
        r = rm.connect()
    except Stop as e:
        tstop(str(e))
    pm = r.GetProjectManager()
    ns = argparse.Namespace(event=None, tavo=False, project=None, export_name=None,
                            live_scoreboard=getattr(a, "live_scoreboard", False))
    spf = 0.95 / 59.94                                    # until measured (prepare-match's estimate)
    ready_said = False
    project_etas(time.time(), spf)
    write_summary()
    for m in MS:
        if os.path.exists(m["export_file"]):
            m["export_state"] = "already there"
            st(f"match {m['n']}: export already there — not redone: {m['export_file']}")
            continue
        try:
            cur = pm.GetCurrentProject()
            if cur and cur.IsRenderingInProgress():
                raise Stop(f"'{cur.GetName()}' is still exporting")
            if not cur or cur.GetName() != m["project"]:
                if cur:
                    cur.DeleteAllRenderJobs()
                    pm.SaveProject()
                if not pm.LoadProject(m["project"]):
                    raise Stop(f"couldn't open project '{m['project']}'")
            r.OpenPage("edit")
            pick = picks[m["n"] - 1]
            ch = rm.parse_choice(pick) if pick else \
                ("option 1: as filmed (no answer for this match)",) + rm.PIC_OPTIONS[1][1:] + ("top",)
            m["picture"] = rm.apply_picture(r, ch)
            st(f"match {m['n']} picture: {m['picture']}")
            ns.export_name = f"zz tournament {m['n']}" if a.test else None
            res = rm.export_waiting(r, ns, m["folder"], lambda s_: st(f"match {m['n']} " + s_))
            st(f"match {m['n']} export: " + rm.last(res))
            if not res.get("ok"):
                raise Stop(f"match {m['n']} export didn't start — " + rm.last(res)[:200])
            t0 = time.time()
            m.update({"export_state": "rendering", "export_file": res.get("file"), "frames": res.get("frames", m["frames"]),
                      "eta": res.get("eta"), "eta_iso": res.get("eta_iso"), "eta_how": "estimate",
                      "eta_end": t0 + m["frames"] * spf})
            project_etas(time.time(), spf)
            write_summary()
            # measure the real speed (~15 % in, 1-6 min), then wait for the end
            mins = m["frames"] / m["fps"] / 60
            cap = 120 if res.get("scoreboard") == "pictures" else 360    # 2026-10-19: steady speed now
            time.sleep(max(60, min(cap, mins * 60 * 0.15)))
            measured = False
            while True:
                s = rm.phase(r, "export_status", ns, m["folder"])
                if s.get("done") or not s.get("rendering"):
                    break
                pct = s.get("percent")
                # 2026-10-09: keep re-measuring — a render can slow down part-way (test: 6 % said 19:08,
                # it ended ~20:00), and the upload reminders go by these times
                if measured and pct and s.get("eta_iso") and not s.get("joining"):
                    old_eta = m.get("eta_said") or m.get("eta_iso")
                    spf = (time.time() - t0) * 100 / pct / m["frames"]
                    m.update({"eta": s.get("eta"), "eta_iso": s.get("eta_iso"), "eta_how": f"measured at {pct}%",
                              "eta_end": t0 + m["frames"] * spf})
                    project_etas(time.time(), spf)
                    write_summary()
                    if old_eta and abs(time.mktime(time.strptime(old_eta[:19], "%Y-%m-%dT%H:%M:%S")) -
                                       time.mktime(time.strptime(m["eta_iso"][:19], "%Y-%m-%dT%H:%M:%S"))) > 600:
                        st(f"match {m['n']}: finish time now ~{m['eta']} ({m['eta_iso']}, {pct}%)")
                        m["eta_said"] = m["eta_iso"]
                if not measured and pct and pct >= 3 and not s.get("joining"):
                    spf = (time.time() - t0) * 100 / pct / m["frames"]
                    measured = True
                    m.update({"eta": s.get("eta"), "eta_iso": s.get("eta_iso"), "eta_how": f"measured at {pct}%"})
                    m["eta_end"] = t0 + m["frames"] * spf
                    project_etas(time.time(), spf)
                    write_summary()
                    if not ready_said:
                        ready_said = True
                        st(f"TOURNAMENT READY FOR APPROVAL — exporting match {m['n']} of {len(MS)}, "
                           f"done ~{m['eta']} ({m['eta_iso']}); all exports done ~{MS[-1].get('eta')}")
                time.sleep(60 if not s.get("joining") else 30)
            ok = bool(s.get("ok"))
            m["export_state"] = "EXPORT OK" if ok else "FAILED"
            m["export_check"] = rm.last(s)
            m.update({"eta": hm(time.time()), "eta_iso": iso(time.time()), "eta_how": "finished"})
            if not ready_said:                             # very short export: done before measuring
                ready_said = True
                st(f"TOURNAMENT READY FOR APPROVAL — match {m['n']} already exported")
            project_etas(time.time(), spf)
            save()
            write_summary()
            st(f"match {m['n']} " + (f"EXPORT OK: {m['export_file']}" if ok else "*** EXPORT CHECK FAILED: " + rm.last(s)))
            if not ok:
                raise Stop(f"match {m['n']} export check failed — " + rm.last(s)[:200])
        except Stop as e:
            m["export_state"] = m.get("export_state") if m.get("export_state") == "EXPORT OK" else "FAILED"
            tstop(str(e))
        except Exception:
            R["crash"] = traceback.format_exc()[-1500:]
            tstop(f"match {m['n']} export crashed — see tournament-result.json")


def tavo_all():
    for m in MS:
        if m["n"] not in (R.get("tavo_list") or []):
            continue
        st(f"match {m['n']} TAVO file …")
        env = dict(UTF8, TAVO_INFO=os.path.join(m["folder"], "_workflow", "youtube-info.json"))
        subprocess.run([PY, W + r"\make-tavo.py"], cwd=W, env=env, creationflags=NOWIN)
        tv = open(W + r"\tavo-log.txt", encoding="utf-8").read().strip().splitlines()
        m["tavo_state"] = tv[-1][9:] if tv else "no log"
        tlog(f"--- match {m['n']} TAVO ---\n" + "\n".join(tv[-6:]))
        st(f"match {m['n']} TAVO: {m['tavo_state']}")
        save()
        write_summary()


# ---------------------------------------------------------------- thumbnail re-pick
def repick(n, cand):
    R2 = json.load(open(TRESULT, encoding="utf-8"))
    m = [x for x in R2["matches"] if x["n"] == int(n)][0]
    env = dict(UTF8, PREP_INFO=os.path.join(m["folder"], "_workflow", "youtube-info.json"),
               PREP_CAND=T + rf"\m{m['n']}\thumb-candidates")
    if (m.get("project") or "").lower().startswith("zz"):
        env["PREP_OUT"] = OC + r"\zz-test-out"
    r = subprocess.run([PY, W + r"\prep-upload.py", "thumbnail", str(cand)], cwd=W, env=env,
                       capture_output=True, text=True, creationflags=NOWIN)
    print(r.stdout + r.stderr)
    th = [l for l in r.stdout.splitlines() if l.startswith("THUMBNAIL: ")]
    if th:
        shutil.copy2(m["thumbnail"], T + r"\approval")


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "thumbnail":
        return repick(sys.argv[2], sys.argv[3])
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--folders", nargs="+")
    ap.add_argument("--event"); ap.add_argument("--ask-event", action="store_true")
    ap.add_argument("--tavo", nargs="?", const="all")
    ap.add_argument("--resume", action="store_true"); ap.add_argument("--test", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--no-picture-check", action="store_true")
    ap.add_argument("--live-scoreboard", action="store_true")   # 2026-10-19: skip the scoreboard pictures
    ap.add_argument("--offset")                  # camera started N s before START: "5" or "1:5,3:2"
    a = ap.parse_args()
    st("TOURNAMENT STARTED " + " ".join(sys.argv[1:]), first=True)
    open(TLOG, "w", encoding="utf-8").write("run-tournament " + time.strftime("%Y-%m-%d %H:%M") + "\n")
    if a.test:
        if not a.folders or not all(os.path.basename(f.rstrip("\\")).lower().startswith("zz") for f in a.folders):
            tstop("--test only on zz test folders")
        os.environ["PREP_OUT"] = OC + r"\zz-test-out"
        os.makedirs(os.environ["PREP_OUT"], exist_ok=True)
    if os.path.isdir(T):                                  # this run's own working copies only
        for x in glob.glob(T + r"\*"):                   # --resume keeps each match's m<n>\ (thumbnail choices)
            if not (a.resume and os.path.basename(x).startswith("m") and os.path.isdir(x)):
                shutil.rmtree(x, ignore_errors=True) if os.path.isdir(x) else os.remove(x)
    os.makedirs(T, exist_ok=True)
    R["args"] = vars(a)
    R["event"] = a.event

    # 0. matches + space
    matches_from_folders(a) if a.folders else matches_from_card(a)
    R["tavo_list"] = list(range(1, len(MS) + 1)) if a.tavo == "all" else \
        [int(x) for x in re.findall(r"\d+", a.tavo or "")]
    st(f"{len(MS)} matches on {R.get('date')}: " + ", ".join(f"{m['n']}) {m['hhmm']} vs {m['team2']}" for m in MS))
    space_check(a)
    copy_gb = 0 if a.folders else sum(m.get("gb", 0) for m in MS)
    approx = time.time() + copy_gb * COPY_S_PER_GB + len(MS) * 6 * 60 + 60
    st(f"plan: copy {copy_gb:.0f} GB (~{copy_gb * COPY_S_PER_GB / 60:.0f} min), set up {len(MS)} matches "
       f"(~6 min each) — approval kit ~{hm(approx)} ({iso(approx)})")
    save()

    announce_offsets(a)                                   # 2026-10-14: goes out with the picture check

    # 1. picture check from the card / folders (before the copy)
    if not a.no_picture_check:
        picture_rows()
        picture_combined()
    if a.dry_run:
        write_summary()
        st("TOURNAMENT DRY RUN DONE")
        return

    # 2. copy, match by match (each match's clips into its own folder)
    if not a.folders:
        for m in MS:
            st(f"copying match {m['n']} of {len(MS)} ({m.get('gb', 0):.1f} GB) …")
            subprocess.run([PY, W + r"\copy-card.py", "--match", m["json"]], cwd=W, env=UTF8, creationflags=NOWIN)
            log = open(W + r"\copy-card-log.txt", encoding="utf-8").read().strip().splitlines()
            tlog(f"--- match {m['n']} copy ---\n" + "\n".join(log))
            if not log or "COPY OK" not in log[-1]:
                tstop(f"card copy, match {m['n']} ({m['team2']}): " + (log[-1][9:] if log else "no log"))
            m["folder"] = log[-1].split(" — ")[-1].strip()
            st(f"copy ok: {m['folder']}")
            save()
        if not R.get("picture_check") and not a.no_picture_check:      # matches without clock times
            for m in MS:
                if not m.get("pic_img"):
                    c = sorted(glob.glob(m["folder"] + r"\DJI_*.MP4"))
                    m["pic_clip"] = c[0] if len(c) == 1 else max(c[:2], key=os.path.getsize)
            picture_rows()
            picture_combined()

    # 3. event, asked once (same as run-match --ask-event)
    if a.ask_event and not R["event"]:
        for i in range(40):
            if fresh(PENDING):
                ev = open(PENDING, encoding="utf-8").read().strip()
                R["event"] = None if ev.lower() in ("", "none", "no", "-") else ev
                break
            if i == 0:
                st("waiting for the event name (event-pending.txt) …")
            time.sleep(15)
        st("event: " + (R["event"] or "none"))

    # 3b. camera-start offsets (2026-10-14): --offset or Kenny's answer; written by run-match into each folder's .json
    resolve_offsets(a)

    # 4. setup + finish, match by match
    for m in MS:
        if a.test:
            m["export_name"] = f"zz tournament {m['n']}"
        if a.resume and os.path.exists(os.path.join(m["folder"], "_workflow", "prepare-state.json")):
            collect_kit(m)
            st(f"match {m['n']}: already set up ({m['project']}) — kept")
            continue
        prepare_one(a, m)

    # 5. one approval kit
    approval_kit()

    # 6. one picture answer for every match
    picks = [None] * len(MS)
    if not a.no_picture_check and (fresh(PIC_ASKED) or fresh(PIC_PENDING)):
        txt = None
        for i in range(41):
            if fresh(PIC_PENDING):
                txt = open(PIC_PENDING, encoding="utf-8").read()
                break
            if i == 0:
                st("waiting for the picture choices (picture-pending.txt) …")
            if i < 40:
                time.sleep(15)
        picks = parse_multi(txt, len(MS))
        R["picture_answer"] = txt
        st("picture choices: " + ("; ".join(f"{k}: {p or 'as filmed'}" for k, p in enumerate(picks, 1))
                                  if txt else "no answer in 10 min — every match as filmed"))

    # 7. exports, one after another; 8. TAVO afterwards
    export_all(a, picks)
    tavo_all()
    okc = sum(1 for m in MS if m.get("export_state") in ("EXPORT OK", "already there"))
    save()
    write_summary()
    st(f"TOURNAMENT EXPORTS DONE — {okc} of {len(MS)} OK" + (" (TAVO done)" if R.get("tavo_list") else ""))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        R["crash"] = traceback.format_exc()[-1500:]
        tstop("run-tournament crashed — see tournament-result.json")
