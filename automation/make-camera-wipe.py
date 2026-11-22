"""
Camera-gap wipe (2026-10-26, the owner; 2026-11-12 drawn by HyperFrames like every other wipe):
the wipe panel with "CAMERA TECHNICAL DIFFICULTY" + a second line (e.g. "3:40 OF SET 1 NOT RECORDED").
    C:\\Python314\\python.exe make-camera-wipe.py <suffix> "<line 1>" ["<line 2>"]
writes set-wipe\\wipe-in-<suffix>.mov + wipe-out-<suffix>.mov (same length as every other wipe,
so place-bookends.py can use them like a SET n wipe) and adds <suffix> to set-wipe.json "labels".
Skipped when the clips already exist with the same text (set-wipe.json "camera_text").
"""
import importlib.util, os, sys, time

W = r"C:\Users\YOURNAME\scoreboard-pipeline"
spec = importlib.util.spec_from_file_location("msw", os.path.join(W, "make-set-wipe.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def main(suffix, line1, line2=""):
    meta = m.load_meta()
    text = line1 + ("\n" + line2 if line2 else "")
    have = all(os.path.exists(os.path.join(m.OUT, f"wipe-{k}-{suffix}.mov")) for k in ("in", "out"))
    if have and (meta.get("camera_text") or {}).get(suffix) == text and suffix in meta.get("labels", []):
        print(f"CAMERA WIPE READY (already made): {suffix}"); return 0
    t0 = time.time()
    try:
        nin, nout = m.make(suffix, {"label": line1, "ghost": "", "sub": line2})
    except Exception as ex:
        print(f"*** CAMERA WIPE FAILED: {ex}"); return 1
    if (nin, nout) != (m.IN_FRAMES, m.OUT_FRAMES):
        print(f"*** CAMERA WIPE LENGTH MISMATCH: {nin}/{nout} vs {m.IN_FRAMES}/{m.OUT_FRAMES}"); return 1
    meta = m.load_meta()
    meta["labels"] = sorted(set(meta.get("labels", [])) | {suffix})
    meta.setdefault("camera_text", {})[suffix] = text
    m.save_meta(meta)
    print(f"CAMERA WIPE READY: {suffix} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
