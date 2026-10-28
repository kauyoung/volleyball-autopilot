"""
offset_tools.py — camera-start offset helpers (2026-10-14, Kenny approved).

"offset" = seconds the camera was already recording before START was tapped
(positive = camera started early). apply-match.lua shifts every score by it
(match.offset in the match .json). copy-card.py measures the gap (camera clip start
minus START tap, whole seconds, negative = camera first) and saves it in the match
folder as copy-info.txt -> start_offset_s.

Used by run-match.py and run-tournament.py:
  suggest(folder)                    None, or {"gap", "offset", "text"} when the gap is beyond
                                     ASK_GAP_S and the folder's .json doesn't already compensate for it
  suggestion_from_gap(gap, existing) same rule from a gap number
  gap_from_clips(rec_starts, clip_starts)   the gap before any copy (same rule as copy-card.py)
  parse_answer(text, suggestion)     Kenny's reply -> (offset or None, note)
  write_offset(folder, value)        writes "offset" into THAT FOLDER'S COPY of the .json only
                                     (the original on Google Drive is never opened for writing)
Nothing here ever applies an offset by itself: callers apply it only with --offset or after a "yes".
"""
import glob, json, os, re, shutil

ASK_GAP_S = 3.0          # gap above this -> suggest / ask


def fmt(v):
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:g}"


def match_json(folder):
    js = glob.glob(os.path.join(folder, "*.json"))          # copy-info.txt is .txt on purpose
    return max(js, key=os.path.getmtime) if js else None


def read_gap(folder):
    try:
        v = json.load(open(os.path.join(folder, "copy-info.txt"), encoding="utf-8")).get("start_offset_s")
        return None if v is None else float(v)
    except Exception:
        return None


def existing_offset(folder):
    try:
        j = match_json(folder)
        return float(json.load(open(j, encoding="utf-8")).get("offset") or 0.0) if j else 0.0
    except Exception:
        return 0.0


def suggestion_from_gap(gap, existing=0.0):
    if gap is None or abs(gap + existing) <= ASK_GAP_S:
        return None
    off = -int(round(gap))
    n = abs(int(round(gap)))
    when = "before" if gap < 0 else "after"
    return {"gap": gap, "offset": off, "text": f"the camera started about {n} s {when} START was tapped"}


def suggest(folder):
    return suggestion_from_gap(read_gap(folder), existing_offset(folder))


def gap_from_clips(rec_starts, clip_starts, tol_s=300):
    """Same rule as copy-card.py: for each START / 'camera recording again' time, the nearest clip start
    within tol_s; the first one found is the 'camera vs phone clock at the start' gap."""
    for s in rec_starts:
        near = [(c - s).total_seconds() for c in clip_starts if abs((c - s).total_seconds()) <= tol_s]
        if near:
            return min(near, key=abs)
    return None


_YES = {"y", "yes", "yep", "yeah", "ok", "okay", "sure", "apply", "do it", "yes please", "go ahead"}
_NO = {"n", "no", "nope", "none", "skip", "0", "-", "no thanks", "don't", "dont"}


def parse_answer(txt, suggestion):
    """-> (offset seconds or None, note). None = don't apply."""
    t = (txt or "").strip().lower().strip(".! ")
    if not t:
        return None, "no answer"
    if t in _YES:
        if suggestion:
            return float(suggestion["offset"]), "yes"
        return None, "yes, but nothing was suggested"
    if t in _NO:
        return None, "no"
    m = re.fullmatch(r"(?:offset\s*)?([+-]?\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?", t)
    if m:
        v = float(m.group(1))
        return (v, "number " + fmt(v)) if v != 0 else (None, "no")
    return None, f"couldn't read the answer '{(txt or '').strip()[:40]}'"


def write_offset(folder, value, allow_any=False):
    """Put "offset": value into the .json copy inside the MATCH FOLDER (original kept once as
    <name>.json.before-offset.txt). Returns (path, old value). Refuses anything that isn't a match folder."""
    if not allow_any and "volleyball matches" not in folder.lower().replace("/", "\\"):
        raise ValueError("not a match folder under 'Volleyball Matches': " + folder)
    j = match_json(folder)
    if not j:
        raise FileNotFoundError("no scorekeeper .json in " + folder)
    data = json.load(open(j, encoding="utf-8"))
    old = data.get("offset")
    bak = j + ".before-offset.txt"
    if not os.path.exists(bak):
        shutil.copy2(j, bak)
    v = float(value)
    data["offset"] = int(v) if v.is_integer() else v
    tmp = j + ".tmp-offset"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    chk = json.load(open(tmp, encoding="utf-8"))
    if chk != data:
        os.remove(tmp)
        raise RuntimeError("offset write did not round-trip")
    os.replace(tmp, j)
    return j, old
