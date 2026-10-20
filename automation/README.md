# Automated match workflow

Everything in the rest of this repo, wired into one hands-off pipeline that an AI
assistant (Claude, driving DaVinci Resolve **Studio** through its scripting API)
runs end to end for each match: from "the card is in the PC" to a finished, approved
4K60 video uploaded Unlisted to YouTube. One short approval message per match; no
editing by hand.

Copy every file in this folder into one working folder (the scripts call each
other by path) and search for `YOURNAME` to set your own paths. Python 3.12+ with
Pillow and NumPy, ffmpeg/ffprobe on PATH, an NVIDIA GPU (NVENC), Resolve Studio
with external scripting set to Local.

## What a run does

| Step | Script(s) | Notes |
|---|---|---|
| Copy the card | `copy-card.py` | Picks the right clips by the scorekeeper's real clock times; measures camera-vs-START offset |
| Set up the project | `prepare-match.py` (phase `setup`), `assemble-match.lua`, `place-scoreboard.lua`, `build-scoreboard.lua`, `apply-match.lua`, `bake-static.lua` | Gap-free 4K60 timeline + the Fusion scoreboard keyed from the match file |
| Plan the cuts | `make-bookends.py` | Trims warm-up, places intro + FINAL screens, cuts set breaks and time-outs (below) |
| Audio | `fix-audio.py` | Joins the camera audio once, loudness-normalises to -14 LUFS (two-pass), ducks the sound under each wipe |
| Intro / FINAL screens | `hf-bookends.py` + `hyperframes/` | HTML/GSAP animations rendered to ProRes 4444 with alpha (download GSAP + CustomEase yourself) |
| Wipes | `make-set-wipe.py` | Diagonal "SET n" / "TIME-OUT" panels that hide each cut |
| Finish | `prepare-match.py` (phase `finish`), `place-bookends.py`, `set-scoreboard-fades.lua` | Puts it all on the timeline; builds the "YouTube cut" timeline |
| Review | `make-review-sheet.py`, `make-picture-check.py` | One contact sheet of every key moment (scores, wipes, cuts) for a single approval; a 4-way brightness/zoom picture check |
| Scoreboard pictures | `scoreboard-stills.py` | See below — makes the export ~2.4x faster |
| Export | `prepare-match.py` (phases `export` / `export_status`), `export-monitor.py`, `join-parts.py` | One H.265 Main10 file; parts + join only as a fallback |
| YouTube | `prep-upload.py`, `make-thumbnail.py`, `thumb-layouts.py`, `youtube-fill.js`, `youtube-finish.js`, `youtube-check.js` | Title/description/chapters, thumbnail, and browser helpers that fill Studio and save **Unlisted** (never Public) |
| Orchestration | `run-match.py`, `run-tournament.py` | One command per match; tournament mode for several matches in a day |
| Safety | `resolve-watch.py`, `archive-matches.py`, `offset_tools.py` | Freeze watchdog, verified copy to an external drive, offset helpers |
| Tests | `zz-test.py`, `make-zz-fixture.py` | End-to-end test on a short fixture, never on real match folders (`--tournament`, `--timeout N`) |

## Highlights

**Scoreboard pictures instead of a live Fusion scoreboard.** A Fusion scoreboard
over 4K60 footage caps a Resolve export near 1x real time and slows it down further
after 15-20 minutes of rendering. `scoreboard-stills.py` reads the comp's keyframes,
renders one EXR (half float, with alpha) per unchanging stretch and EXR frames only
for the animated moments, lays them on a track directly above the live scoreboard
and switches the live one off. Result on a 90-minute match: ~114 fps steady instead
of 47 fps falling to 30 fps, and the picture matches the live scoreboard to within
0.12/255. Every build is verified (coverage, re-rendered sample frames, a whole-frame
comparison); anything unexpected falls back to the live scoreboard automatically.

**Set breaks and time-outs cut automatically.** The scorekeeper app has a one-tap
**Time-out** button. The video cuts from 5 s after the tap to 5 s before the
referee's next **serve whistle**, which `whistle.py` finds in the camera audio (a
long, loud, pure ~3.3-3.7 kHz tone; the rally-ending whistle is short). Set breaks
restart the same way. No clear whistle: fixed fallbacks (40 s / 60 s before the
next point). Each cut is covered by a diagonal wipe, with the sound ducked
underneath and the scoreboard hidden and faded back in.

**One approval per match.** The review sheet, thumbnail and YouTube text go out
as soon as the timeline is finished, with an estimated export end; the upload
happens only after approval.

## Resolve scripting quirks worth knowing

- `Timeline.SetTrackEnable` / `GetIsTrackEnabled` are unreliable; `TimelineItem.SetClipEnabled` works.
- `Timeline.DeleteTrack` only works on the current timeline; `AddTrack("video", {"index": n})` inserts at n.
- Stills appended with `MediaPool.AppendToTimeline` are always 300 frames; an append in front of an existing clip is trimmed to the gap (place right to left).
- Image sequences: `startFrame` is the source frame number, `endFrame` is exclusive.
- Changing a Fusion Loader's clip by script can pop a modal dialog that blocks the API.
