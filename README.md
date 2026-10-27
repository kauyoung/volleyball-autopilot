# DIY Volleyball Scoreboard Overlay Pipeline

A from-scratch pipeline for putting a live, animated scoreboard overlay on
volleyball match footage — built for parents/coaches recording their own
team's games with a 4K60 action camera and DaVinci Resolve, without paying
for a subscription filming/scoring service.

![The scoreboard overlay on a 4K match frame, at match point in set 2](docs/scoreboard-preview.jpg)

*A frame rendered by this pipeline: match point in set 2. Team names are made up, and the gym footage
is blurred because the players are minors.*

End to end: record on a 4K60 camera → convert footage to an editing-friendly
codec → assemble the clips into one gapless timeline in DaVinci Resolve →
score the match on a phone or laptop (live at the game, or later during
editing) → apply that scoring data onto a scripted Fusion scoreboard graph →
render.

The scoreboard shows: live score, sets won, current set number, which team
is serving, SET POINT / MATCH POINT tags and an optional team logo, with
broadcast-style motion (score pops, fades, set-change transitions) — built
once as a reusable Fusion composition, then driven entirely by a JSON file of
timestamped scoring events.

![Close-up of the scoreboard bar: team names, sets won, current set, score and the serve indicator](docs/scoreboard-closeup.png)

## Why this exists

Paid scoreboard-overlay apps for phone recording exist, but they cap out at
1080p30 and bake the overlay into the video permanently. This pipeline
keeps the camera and the scoreboard as two independent layers — shoot in
4K60, keep raw footage untouched, and the overlay lives in an editable
Fusion composition until final render.

## Requirements

- A 4K60-capable camera (this was built around a DJI Osmo Action-series
  camera; any camera producing MP4/MOV/MXF files works with the assembly
  script).
- **DaVinci Resolve** — the manual workflow in `resolve-scripts/` is Lua run from
  Resolve's own Console and is meant to work on the free edition. The hands-off
  pipeline in `automation/` needs **DaVinci Resolve Studio**: it drives Resolve
  from outside with Python (Studio-only since Resolve 21.1) and exports 10-bit
  H.265 with NVIDIA hardware encoding (also Studio-only). One thing to know up front: a
  new project's **Playback frame rate** setting (Project Settings → Master
  Settings) defaults to 24 and is separate from **Timeline frame rate** — if
  your live preview plays back in obvious slow motion despite everything
  else looking correct, that mismatch is almost always why. Exports are
  unaffected either way; it's a preview-only setting.
- **DaVinci Resolve Studio** (optional): Studio decodes HEVC/H.265 natively on
  Windows, so if you have it you can skip the conversion step entirely and
  import the camera files as-is.
- **ffmpeg** on your PATH (only needed if your camera shoots HEVC/H.265 and
  you're on the free edition — see `convert-footage.bat` below). Free
  download from ffmpeg.org.
- **Font**: the scoreboard uses **Barlow Condensed** (SemiBold for scores and
  labels, Bold for team names) — free under the SIL Open Font License from
  Google Fonts, so it's fine for YouTube. Install it for your Windows user
  (or all users) before running the builder. Team names are shown in capitals
  (`NAMES_UPPERCASE`). To use another font change `FONT` / `NAME_FONT` in
  `build-scoreboard.lua` and re-measure `NAME_CHAR_W` (see Known limitations).
- **Python 3 + Pillow** (optional, only for `tools/make-thumbnail.py`).
- An Nvidia GPU is used for hardware-accelerated video conversion
  (`h264_nvenc`) in `convert-one.ps1`. Without one, edit that file to use
  software encoding (`libx264`) instead, or every conversion will fail.
- The `.bat` / `.ps1` conversion tooling is Windows-specific. The Lua
  scripts and the scorekeeper web app are platform-independent (Resolve's
  scripting console and any browser).

## What's in this repo

```
├── automation/          The full hands-off workflow (Resolve Studio + an AI assistant) — see automation/README.md
├── resolve-scripts/     Lua scripts run from DaVinci Resolve's Console (manual workflow)
├── footage-conversion/  Windows HEVC→H.264 converter (.bat + .ps1)
├── scorekeeper/         The scorekeeping web app + optional Google Drive receiver
├── assets/              Serve-ball icons used by the overlay
├── tools/               YouTube thumbnail generator
└── docs/                Manual walkthrough + a sample match file
```

| File | What it does |
|---|---|
| `footage-conversion/convert-footage.bat` | Double-click-to-run converter. Finds the newest dated match folder, converts every `DJI_*.mov`/`.mp4` from HEVC to H.264 (hardware-accelerated), preserves exact filenames, keeps the originals in a `raw_originals` backup folder. Safe to re-run — skips anything already converted. |
| `footage-conversion/convert-one.ps1` | Helper script `convert-footage.bat` calls per clip — shows a live percent/ETA progress bar during conversion. Not meant to be run by hand. |
| `resolve-scripts/assemble-match.lua` | Run once per match from Resolve's Console. Imports every clip from the newest match folder and builds a gap-free timeline at the right resolution/frame rate. Prints a verification report — total length vs. sum of source clips, and a chapter-order sanity check — so a bad import shows up as text instead of a silent, drifting overlay. |
| `resolve-scripts/build-scoreboard.lua` | Builds the entire scoreboard's Fusion node graph from scratch: bar, score cells, team names, sets, serve indicator, "SET n" tab, SET POINT / MATCH POINT tags, optional team logo, outline, sheen, drop shadow and an overall fade. Team names are anchored on their outer edge, so both sit the same distance from the ends of the bar whatever their length. Look is configurable at the top (`BAR_WIDTH`, `BAR_RAISE`, `PILL_STYLE`, fonts, colours). Run once per match. |
| `resolve-scripts/apply-match.lua` | Reads a match JSON file (see below) and writes keyframes onto the nodes `build-scoreboard.lua` created — score, sets, set number and serve indicator as instant "step" changes, plus the motion (score/sets pops, SET POINT / MATCH POINT tags worked out from the score, set-change dips, fade in/out). Also sets the team names from the file and **automatically re-aligns each set to its clip join** (see below). |
| `resolve-scripts/run-overlay.lua` | Convenience wrapper — runs `build-scoreboard.lua` then `apply-match.lua` back to back. |
| `scorekeeper/volleyball-scorekeeper.html` | Self-contained scorekeeping web app with a guided, one-screen-at-a-time flow simple enough for anyone at the gym: who's playing → press record + START → two giant team buttons with a 5-second UNDO → automatic set-over screen → FINISH MATCH. Timestamps every event, survives the page being closed mid-match, and exports the JSON file the Lua scripts consume — or sends it to Google Drive automatically (below). A one-tap **Time-out** button (cleared by the next point) records time-outs so the automated workflow can cut them out. |
| `scorekeeper/scorekeeper-drive-upload.gs` | Optional Google Apps Script "web app" that receives the match file from the scorekeeper and saves it into a Drive folder, so nobody has to export or email anything. |
| `tools/make-thumbnail.py` | Builds a 1280×720 YouTube thumbnail from the match file and a frame of the finished video: date, team names, team logo, and one score tile per set. |
| `assets/volleyball-serve-icon-bold.png` | The serve-indicator icon `build-scoreboard.lua` places on whichever team is serving (bold version, used by default). `volleyball-serve-icon.png` is the original thin-line version. |
| `docs/fusion-scoreboard-walkthrough.md` | Manual, click-by-click guide to building the same scoreboard graph by hand in Fusion — useful for understanding what the script automates, or for customizing the look yourself. |
| `docs/match-sample.json` | A synthetic example match file (not a real game) showing the data format `apply-match.lua` expects. |

## Fully automated workflow

The `automation/` folder holds the current, end-to-end version of this pipeline: one
command per match copies the card, builds the project and scoreboard, trims the
warm-up, cuts set breaks and time-outs (restarting just before the referee's serve
whistle, found in the audio), normalises the sound, adds intro/FINAL screens,
renders a review sheet for a single approval, exports one 4K60 10-bit H.265 file
about 2.4x faster than with a live Fusion scoreboard (by pre-rendering the
scoreboard as pictures), and prepares the YouTube upload. Details:
[automation/README.md](automation/README.md). The manual workflow below still works
on its own.

```mermaid
flowchart LR
    A["📱 Scorekeeper app<br/>one tap per rally"] -->|FINISH MATCH| B[("Google Drive<br/>match file")]
    C["🎥 Camera card<br/>4K60 clips"] --> D["copy-card.py<br/>picks the clips by clock time"]
    B --> D
    D --> K[("Backup drive<br/>verified copy")]
    D --> E["Resolve: setup<br/>timeline + Fusion scoreboard"]
    E --> F["Resolve: finish<br/>cuts, audio, intro / FINAL, wipes"]
    F --> G{"Review sheet<br/>one approval"}
    G -->|approved| H["Export<br/>scoreboard pictures, H.265"]
    H --> I["YouTube<br/>Unlisted"]
    H --> J["TAVO file<br/>4K H.265"]
```

<p align="center">
  <img src="docs/intro-screen.jpg" width="49%" alt="Intro screen: season label, both teams with ball badges, VS, date, best of 3, sets to 25">
  <img src="docs/final-screen.jpg" width="49%" alt="FINAL screen: set scores, sets won, winner line, total points, longest run, biggest lead, match time">
</p>
<p align="center"><sub>The intro and FINAL screens (<code>automation/hyperframes/</code>), filled in automatically from the match file. Made-up teams; teams without a logo get the ball badge.</sub></p>

## Setup

Copy the contents of `resolve-scripts/` to wherever you want to run them
from (they don't need to stay inside a cloned repo). Each script has a
small `CONFIG` section near the top — edit these to match your own machine:

- **`assemble-match.lua`** — `CLIP_ROOT` (the folder containing your dated
  match folders) and `WORK_DIR` (where you copied these scripts to, used
  for logs and the printed next-step commands).
- **`apply-match.lua`** — same `MATCH_ROOT` / `WORK_DIR` idea.
- **`run-overlay.lua`** — `BASE`, the folder you copied these scripts to.
- **`build-scoreboard.lua`** — `SERVE_ICON_PATH` (point this at wherever
  you save `volleyball-serve-icon-bold.png` — somewhere permanent, not a
  Downloads folder that gets cleared), `LOGO_DIR` (optional team logos, see
  below) and `TEAM1_NAME` / `TEAM2_NAME` (only used when run on its own;
  `run-overlay.lua` passes the names from the match file).
- **Team logo (optional)** — put a transparent PNG named after your team in
  `LOGO_DIR` (lower-case, spaces as dashes: `home-team.png` for "Home Team").
  It appears at the outer end of your team's side of the bar and the name
  shifts inward to make room. No file, no logo.
- **Colours** — `GREEN` (your team) and `BLUE` (opponent) near the top of
  `build-scoreboard.lua`, with the matching `TEAM_RGB` in `apply-match.lua`
  and `--team1` / `--opp` in the scorekeeper. Light colours read best as
  text on the dark bar.

Every placeholder path in the scripts is written as an obvious
`C:/Users/YOURNAME/...`-style string — search for `YOURNAME` if you want
to find every line that needs a personal value.

## Workflow

1. **Record** at 4K60 (or whatever resolution/frame rate you configure the
   timeline to match).
2. **Copy the card** into a dated folder under your configured match root.
   **Convert** only if your camera shoots HEVC and you're on the free
   edition: double-click `footage-conversion/convert-footage.bat`. (Resolve
   Studio reads HEVC directly — skip this.)
3. **Assemble**: open a new, empty Resolve project (frame rate can't change
   once a timeline exists) and run `assemble-match.lua` from the Console.
   Read its verification output before continuing — a reported gap or
   out-of-order chapter list means don't trust the timeline yet.
4. **Add the overlay track**: add a Fusion Composition to track V2 (drag
   any item from Effects Library → Fusion Generators — not Solid Color,
   which looks similar but doesn't carry a Fusion page comp), then resize
   it to span the whole timeline. Resolve's scripting API can't do this
   part reliably, so it's a manual step.
5. **Score the match**: open `scorekeeper/volleyball-scorekeeper.html` and
   follow the screens — either live at the game (press record on the camera,
   then START) or later during editing (play the assembled timeline back at
   1x speed and tap along). Tap the big team button when a team wins a
   rally; a 5-second UNDO bar catches mis-taps. When a set is won the app
   switches to a set-over screen: stop the camera and tap **I stopped the
   camera** (or **Camera is still recording** if you keep rolling), then tap
   **Camera is recording again** when play resumes. Mid-set camera stops,
   removing a point and ending early are under **More options**. When the
   match is won, tap **FINISH MATCH** — the file is sent to Google Drive
   automatically if you set that up, and **Export match file** is always
   there as a backup.

   <p>
   <img src="docs/scorekeeper-setup.png" width="260" alt="Scorekeeper setup screen: our team, opponent, and the match format (sets to 25 or 15, best of 3, 2 sets, scrimmage)">
   &nbsp;
   <img src="docs/scorekeeper-live.png" width="260" alt="Scorekeeper during a set: one big button per team showing the score, recording timer, Time-out and More options">
   </p>
6. **Build and apply the scoreboard**: with the Fusion Composition clip
   selected and the Fusion page open, run `run-overlay.lua` from the
   Console.
7. **Check before rendering**: scrub to the start (0-0, Set 1, no serve
   ball shown), scrub to somewhere late in the match (score should match
   the play on screen — this is what catches assembly errors), and check
   the final frame (correct winning score and sets tally).
8. **Render.** For YouTube, H.265 at roughly 30–35 Mbps (4K60) keeps close
   to the camera's quality at about two-thirds the size of an equivalent
   H.264 file. Save it as a render preset so every match exports the same.
9. **Thumbnail (optional)**: grab a frame from the finished video and run
   `python tools/make-thumbnail.py match.json frame.jpg thumbnail.jpg`.
   YouTube chapters need at least three timestamps, starting at 0:00 — for
   a two-set match add a third (e.g. "Match point").

## Google Drive auto-upload (optional)

1. Create a new project at script.google.com, paste in
   `scorekeeper/scorekeeper-drive-upload.gs`, and change `SECRET_KEY` to a
   long random string (and `FOLDER_NAME` if you like).
2. Deploy → New deployment → Web app, execute as **Me**, access **Anyone**.
   Authorize it, and copy the web-app URL (ends in `/exec`).
3. In `volleyball-scorekeeper.html` set `DRIVE_URL` to that URL and
   `DRIVE_KEY` to the same secret, then host the page (e.g. Netlify drop).

At FINISH MATCH the phone sends the match file; if there's no signal it keeps
it and retries automatically (on reopen, when back online, when the page
returns to the foreground) until Drive confirms. If you change the script
later, redeploy it as a new version or the old one keeps running.

## Scoreboard design

- Bar raised about 10% up the frame (`BAR_RAISE`) so YouTube's player
  controls, which cover the bottom ~8% when the video is paused, never hide it.
- "SET n" sits in a tab joined to the top of the score box (`PILL_STYLE =
  "tab"`), the same shade as the score box, with a faint outline around bar
  and tab that lines up with the cell separators. `"float"` and `"clean"` are
  alternative floating-pill styles.
- SET POINT / MATCH POINT tags (floating pills in the team's colour) are
  worked out from the score after every rally — deuce handled, set 3 to 15.
- Motion: the scoring team's number pops and flashes its colour, the sets
  number does the same when a set is won, tags fade in/out, the set number
  and scores dip out and back in at a set change, and the whole scoreboard
  fades in and out at the start and end of the video.

<p align="center"><img src="docs/scoreboard-animation.gif" width="800" alt="Scoreboard animation: SET POINT tag fades in, the winning point pops, the sets number pops, the set number and scores dip into set 2, then MATCH POINT appears"></p>
<p align="center"><sub>Set point, set won, the change to set 2, and match point (a made-up match, sped up between rallies).</sub></p>

## Automatic set alignment

Every set break is a camera stop, so every set after the first begins at a
clip join on the timeline. If Stop/Resume Recording was tapped a few seconds
early or late, every score in that set is off by the same amount — which a
single global offset can't fix. `apply-match.lua` measures where each set's
0–0 falls in the data against where its clip join actually is, and shifts
that whole set by the difference. It reports each shift, and skips itself
(with a message) if the number of set breaks doesn't match the number of
clip joins — i.e. the camera was also stopped mid-set — or if a shift would
be larger than `ALIGN_MAX_SEC`. The match file itself is never modified.

Cameras that split long recordings into chapter files (DJI splits at about
16 GB, ~18–21 min of 4K60) produce clip joins that aren't camera stops. Those
are recognised from the filenames (the next file starts exactly where the
previous one ended) and ignored, so recording straight through a match works
too.
Turn it off with `AUTO_ALIGN_SETS = false`.

## Known limitations

- **A converter can silently scramble clip order.** Some converters rename
  files with an altered embedded timestamp, which can throw off Resolve's
  media-pool import order (it doesn't preserve the order clips are handed
  to it in). `assemble-match.lua` guards against this by sorting on the
  camera's own embedded chapter number rather than trusting import order,
  and prints an explicit ascending-order check.
- **Fusion Composition placement can't be scripted.** Resolve's API can
  insert a Fusion composition onto a timeline, but always at a fixed
  position on track V1 with no resize/reposition API available — placing
  it on V2 and stretching it to fit has to be done by hand (see step 4
  above).
- **An accidental mid-set "camera stopped" in the scorekeeper app can't be
  undone** — the excluded time is baked into every timestamp logged after
  it. It's tucked under More options behind a two-tap confirm, and
  automatic set alignment corrects mistimed taps at set breaks.
- **Team names are width-estimated for truncation.** Positioning is exact
  (edge-anchored), but the "too long, add ..." check uses an average
  character width calibrated for Barlow Condensed Bold in capitals. If you change
  `NAME_FONT`, re-measure `NAME_CHAR_W` in both `build-scoreboard.lua`
  and `apply-match.lua`.
- Team names longer than about 21 characters (about 16 on the side with a
  logo) get automatically truncated with "..." so they don't overlap the
  serve-ball icon. The scorekeeper warns about long names when you type them.
- The serve ball fades in/out over a few frames rather than cutting
  instantly. Cosmetic only.

## License

MIT — see `LICENSE`. Use it, fork it, adapt it for other sports (the
scorekeeping logic in `volleyball-scorekeeper.html` is volleyball-specific:
25-point sets, best of 3 — everything else in the pipeline is sport-agnostic).
