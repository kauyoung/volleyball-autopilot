HyperFrames screens used by the match workflow. Design: 2026-11-12 motion redo (dark 14-degree panel v2).
  team-intro  + team-final : rendered by hf-bookends.py (make-bookends.py render intro|summary).
  team-wipe                 : rendered by make-set-wipe.py / make-camera-wipe.py (SET n, TIME-OUT, camera gap);
                               wipe.js holds the words; 173 frames = 53 wipe-in + 120 wipe-out.
All three: laid out at 1920x1080, drawn at 4K (#scene zoom 2), shared motion.js + base.css (keep the three
copies identical). Timing that the scripts rely on - do not change without changing them too:
  intro 4.9 s, everything landed by 3.145 s, still frame 3.145-3.195 s (the workflow repeats it for the hold);
  FINAL 6.9 s (the workflow holds the last frame); wipe covered on frames 48-125.
match.js / wipe.js are rewritten by the scripts. index.html?p=1 in Chrome = 1080 preview over a stand-in plate.
_renders\ holds the last raw renders (safe to delete). Previous design: _backup-2026-11-12-motion-redo\.
