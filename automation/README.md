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
| Team logos | `logo_sizes.py` | Every logo is sized by its visible drawing (not its image canvas; near-black edges ignored) so all logos look the same size on the scoreboard and the intro/FINAL; optional per-logo factor in `team-logos/logo-sizes.txt` |
| Wipes | `make-set-wipe.py` | Diagonal "SET n" / "TIME-OUT" panels that hide each cut |
| Finish | `prepare-match.py` (phase `finish`), `place-bookends.py`, `set-scoreboard-fades.lua` | Puts it all on the timeline; builds the "YouTube cut" timeline |
| Review | `make-review-sheet.py`, `make-picture-check.py` | One contact sheet of every key moment (scores, wipes, cuts) for a single approval; a 4-way brightness/zoom picture check |
| Scoreboard pictures | `scoreboard-stills.py` | See below — makes the export ~2.4x faster |
| Export | `prepare-match.py` (phases `export` / `export_status`), `export-monitor.py`, `join-parts.py` | One H.265 Main10 file; parts + join only as a fallback |
| YouTube | `prep-upload.py`, `make-thumbnail.py`, `thumb-layouts.py`, `youtube-fill.js`, `youtube-finish.js`, `youtube-check.js` | Title/description/chapters, thumbnail, and browser helpers that fill Studio and save **Unlisted** (never Public) |
| Orchestration | `run-match.py`, `run-tournament.py` | One command per match; tournament mode for several matches in a day |
| Safety | `resolve-watch.py`, `archive-matches.py`, `offset_tools.py` | Freeze watchdog, verified copy to an external drive, offset helpers |
| Tests | `zz-test.py`, `make-zz-fixture.py` | End-to-end test on a short fixture, never on real match folders (`--tournament`, `--timeout N`, `--team2 "<name>"` to check a long name or a logo) |

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
- NVENC render bit rate can't be set from a script (`SetRenderSettings({"VideoQuality": ...})` is refused for the NVIDIA encoders) - save it in a render preset in the Deliver page instead.

## Tournament-day additions (October 2026)

Lessons from the first full tournament (five matches in one day) went straight back into the pipeline:

- **Camera stops are handled automatically** (`camera-time.py`). The scorekeeper now saves the real clock time of every tap; the pipeline places each point on the camera timeline from those clock times and the camera's file times. A stop inside a set gets a "CAMERA TECHNICAL DIFFICULTY - M:SS OF SET n NOT RECORDED" wipe (`make-camera-wipe.py`); a stop between sets puts the SET n wipe on the restart.
- **Tournament options**: per-match opponent names and stage labels (`run-tournament.py --team2 "2:Name" --stage "1-4:Pool Play,5:Play Off"`), one review sheet per match, and uploads that start by themselves after approval while the next match exports.
- **Re-runs**: `run-match.py --rebuild` (next free project version), `--picture N`, `--export-only`.
- **YouTube titles** read `vs <Opponent> | <event · stage> | <date>`.
- **TAVO files**: 4K H.265, optional brightening, the same time-out cuts as the YouTube video.
- **Scoreboard fixes**: several events on one frame no longer ramp the serve ball in; tied stats show "EACH".
- **Higher-bit-rate YouTube export** (60 Mbps preset) so YouTube's own re-encode starts from a cleaner file.

## Score-timing and tournament fixes (November 2026)

A second tournament exposed a few weak spots; each one is now handled automatically and tested on that day's footage:

- **Scores line up with the camera's own clock** (`camera-time.py`). The camera usually starts recording a few seconds before the scorekeeper's START tap (record in the camera app, wait for the beep, switch back, tap START). Clip 1 is now placed by the camera's clock (synced to the phone by the camera app) and later clips by the camera's frame-accurate timecode, so any wait between record and START - 3 s, 20 s or 2 minutes - gives the same, correct timing. A timecode jump after a camera restart is detected and falls back to the file times.
- **The phone double-checks the camera clock.** The scorekeeper silently notes when its page goes to the background and comes back (phone clock). The camera must have started recording while the page was in the background; if it did, the clock is confirmed. If not, the camera clock is off and the timing is rebuilt from the phone's estimate, refined by the video.
- **Per-set timing check** (`sync-check.py`): averages how much the picture moves around every score tap and compares the pattern with an approved match (`sync-template.json`). Rallies repeat roughly every 20 s, so this check only confirms timing that is already close - it cannot find a large clock error on its own, which is why the phone check and an "unusual wait - right?" question exist.
- **Uploads wait when the timing is in doubt**: in tournament mode a match whose timing check is flagged is held back from YouTube until the owner confirms (`upload-approved.txt` with `sync-ok`).
- **Picture check across camera restarts** (`picture-joins.py`): after an SD-card stop the camera can come back in another lens mode or profile (wider, darker). Every restart is compared with the picture before it (layout + brightness, three frames each side) and flagged with a before/after image; the fix goes in a per-clip `clip-fix.txt` (zoom, pan, tilt, brightness) that both the YouTube export and the TAVO file use.
- **Time-outs**: a second tap in the scorekeeper means "Time-out over" and the video restarts 3 s before it (else the serve whistle, else 60 s). A camera stop during a time-out is covered by the time-out cut; a mid-set stop shorter than 20 s is a plain cut.
- **Format and name corrections**: `--two-sets` (a 2-set match scored as best of 3 by mistake), `--age 15U` (age group in YouTube titles only).
- **Robustness**: a hidden Resolve dialog (often off-screen after a monitor change) blocks all scripting - the run now stops and says so; the intro/FINAL renderer retries once; an edited cut list is always the one exported; the camera card copies in the background so match 1 starts as soon as its clips are in.
