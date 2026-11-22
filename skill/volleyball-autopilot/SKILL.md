---
name: volleyball-autopilot
description: Runs the Volleyball Autopilot match-video pipeline (DaVinci Resolve Studio on Windows) - first-time team setup, single matches, tournament days, uploads to YouTube. Use when the user says "set up volleyball autopilot", "start the volleyball workflow", "process the match", "tournament day", "upload the volleyball video", or asks about the match video, scoreboard or TAVO file.
---

# Volleyball Autopilot run sheet

`W` = the work folder in `team-config.json` (`work_folder`); `PY` = its `python`. The repo clone (github.com/kauyoung/volleyball-autopilot) is
never edited: `team-setup.py` writes the working copy into W. Speak plainly; the user is a parent, not a programmer. One short message per step.

## Tools
- Claude desktop app on the Windows PC, with W connected as a folder (device_bash reads logs there) and the **DaVinci Resolve Studio MCP**
  (`run_script_unsafe`: runs Python on the PC, needs Resolve open). Long jobs: `exec(open(W + r"\launch.py").read()); launch([PY, script, ...])`.
- Waiting = `send_later`, then end the turn. On every wake-up read the status file first so nothing is done twice.

## First run: no `team-config.json` in W -> setup interview (do this before any match)
1. Say what setup does (about 30-60 min once: answer a few questions, install a few free tools, sign in to YouTube once).
2. Ask, in two short rounds (multiple-choice where it helps):
   - Team name exactly as on the scoreboard ("Riverside Rapids"), age group ("14U"), a short code of up to 8 letters for the FINAL
     screen ("RAPIDS"), the team colour (hex, or describe it and suggest a hex that reads well on a dark bar; opponent stays sky blue
     unless they ask), the team logo (ask them to attach it or give its path; transparent PNG is best).
   - Folders: work folder (default `C:\Users\<them>\scoreboard-pipeline`), the drive letter for footage (a big drive), an archive drive
     letter (optional), where Google Drive for desktop shows "My Drive" (e.g. `G:\My Drive`).
   - YouTube: the channel name to upload to, the season playlist title (and its ID if they know it), and whether videos with nothing
     flagged may upload by themselves (auto-upload) or always wait for their OK.
3. Repo: if there is no clone yet, help them get one (`git clone https://github.com/kauyoung/volleyball-autopilot` or the green Code ->
   Download ZIP button) somewhere OTHER than the work folder. Ask them to connect the work folder in the Claude app (+ -> Add folder).
4. Write `team-config.json` (fields as in `automation/team-config.example.json`) next to `team-setup.py`, then run
   `PY automation\team-setup.py --config ...` through run_script_unsafe. If they chose auto-upload, write `on` into `W\auto-upload.txt`.
5. Go through every `MISSING` line ONE at a time, with plain steps, re-running `team-setup.py --config team-config.json --check` after each:
   Python 3.12+ and the pip packages it names; ffmpeg; Resolve Studio with Preferences > System > General > External scripting = Local;
   Barlow Condensed font; Node.js LTS; GSAP + CustomEase files into the three `hyperframes\team-*` folders; Google Drive for desktop and the
   folder "Volleyball Matches – Scorekeeper"; YouTube: a Google Cloud project with "YouTube Data API v3", OAuth client "Desktop app",
   consent screen External + In production, its JSON saved as `W\_youtube-api\client_secret.json`, then
   `PY yt-upload.py auth --channel main` - THEY sign in in the browser and pick their channel (never ask for or type passwords).
6. Scorekeeper: the phone app is `scorekeeper/volleyball-scorekeeper.html` in the repo. For uploads to their Drive they deploy their own
   copy (Netlify or GitHub Pages) with their own Apps Script (`scorekeeper-drive-upload.gs`) and set its URL + key in the page; until then
   they can share the match file to Drive from the phone. Explain the record-then-START habit: press record on the camera, then tap START
   in the app within 10 s.
7. `SETUP OK` -> practice run: `PY make-zz-fixture.py "<a 5-min clip of theirs>"`, then `launch([PY, W+r"\zz-test.py"])`; the last line of
   `zz-test-status.txt` must be `ZZ TEST PASSED`. Then tell them they're ready, and how a match day goes (below) in five lines.
Re-run `team-setup.py` whenever they change team details, colours, the playlist (new season) or update the repo (`git pull`).

## Triggers
- "start the volleyball workflow" -> single match (2+ match files today, or they say tournament -> tournament).
- "upload the volleyball video" -> Upload. Flags from what they say: event -> `--event "<event>"`; none and not a scrimmage ->
  `--ask-event`. "with TAVO" -> `--tavo`. Two sets scored as best of 3 -> `--two-sets`. Time ran out in the last set and they say their
  team won -> `--winner 1`. Someone else scored on their own phone -> `--other-scorer`. Opponent age only via `--age 15U` when the name
  doesn't end in it. Always `--picture 1` unless they pick another picture option.

## Rules on every run
- Every run starts with a pre-flight line (`PREFLIGHT OK` / `PREFLIGHT MISSING: ...`, also `preflight.txt`): tell them the whole list at once.
- WATCHDOG: `send_later` checks every 10 min for the whole run (copy, setup, finish, exports, uploads) until `RUN DONE` /
  `TOURNAMENT EXPORTS DONE`. Each wake: `tail -2 <run-match|tournament>-status.txt; tail -1 resolve-watch.txt`. A STOPPED line or Resolve
  GONE/FROZEN -> message them that minute. `RESOLVE CRASHED during ...` -> ask them to reopen Resolve from the Start menu (no project); the
  run waits 30 min and carries on by itself (`recovered: ...`).
- A STOPPED line names the cause and ends with `rerun: <command>` - use that command. `--resume` skips copied clips and makes missing items.
- Approval: as soon as the status says READY FOR APPROVAL, send the review sheet (read the small one yourself and check every row),
  thumbnail, YouTube text and every FLAG in plain words. Auto-upload on (`auto-upload.txt` = on): matches with no FLAG and an OK timing
  check upload by themselves - say which, and that "hold" stops them (`upload-hold.txt` = `hold` or match numbers). Flagged matches, or
  auto-upload off: upload only after their OK (`upload-approved.txt` = `ok` / `all` / `1,3`, plus ` sync-ok` when they cleared a timing flag).
- Every upload: Unlisted, never Public, to the channel named in team-config.json. Anything else -> ask.
- Never: delete or overwrite camera files, exports or thumbnails; delete anything on YouTube; enter passwords; start or quit Resolve
  during a match run (only the user does); run copy-card through the 60 s script tool; edit the Drive original of a match file.
- Problems: report first, fix after their OK. Read only the files named here; logs with `tail`/`grep`, never whole.

## Single match
0. One run_script_unsafe: list today's match files in the Drive folder; then `launch([PY, W+r"\run-match.py", "--auto-finish",
   "--picture", "1", ...flags])` (+ `--recent` when more than one file is from today). One message: copying N GB, approval about HH:MM.
1. Watchdog. On READY: `cat run-summary.txt`; stage `_overlay_check\approval-small\review-sheet-small.jpg` and the files on its
   `approval kit:` line; send the approval message (flags, time-outs cut, camera stops, the record->START gap, export done about HH:MM).
2. After their OK (or auto-upload): `uploading` must follow the `EXPORT OK` within minutes. `RUN DONE — EXPORT OK, UPLOAD OK <url>` ->
   one line with the link. The archive to the archive drive starts by itself; when `archive-log.txt` ends `ARCHIVE OK` the camera card can
   be formatted in the camera (never delete clips on the PC).

## Tournament
0. First message: who scored (their phone or someone else's), then one numbered list from today's match files - time, opponent + age,
   stage (Pool Play / Play Off), TAVO yes/no, event - to confirm in one reply. `PY preflight.py --tournament` first: Resolve open more than
   30 min -> ask them to restart it before launching.
1. `launch([PY, W+r"\run-tournament.py", "--no-picture-check", "--event", ..., "--stage", "1-4:Pool Play,5:Play Off", ...])`
   (`--team2 "2:<name>"`, `--age`, `--two-sets 3`, `--winner "3:1"`, `--other-scorer all`, `--tavo 1,3` as needed).
2. Watchdog. On `TOURNAMENT READY FOR APPROVAL`: read ONLY the `claude sheet:` image (all matches side by side), send the per-match kit
   files (`match N - ...`) with flags per match. One OK covers all. Uploads run one at a time while the next match exports.
3. `TOURNAMENT EXPORTS DONE` -> TAVO (if asked) -> archive (automatic) -> "safe to format the card".

## Upload by hand (fallback, re-uploads, edits)
- Upload: `launch([PY, W+r"\yt-upload.py", "upload", "--channel", "main", "--expect-channel", "<channel>", "--video", <mp4>,
  "--text", <"... - YouTube text.txt">, "--thumb", <"... - thumbnail.jpg">, "--playlist", "<playlist>"])`; result in yt-upload-status.txt.
- Change title/description/thumbnail: `PY yt-upload.py update --channel main --expect-channel "<channel>" --video-id <id> --text ... --thumb ...`

## When something is off
| What you see | Do |
|---|---|
| `PREFLIGHT MISSING` | Tell them the whole list; rerun when fixed |
| `RUN STOPPED` / `TOURNAMENT STOPPED` | Tell them the cause; run the `rerun:` command after their OK |
| `RESOLVE CRASHED during ...` | Ask them to reopen Resolve; the run carries on (`recovered:`) |
| `camera clip check failed` / `camera clips changed during finish` | Nothing bad was exported; rebuild that match (`--folder ... --rebuild`) |
| Any timing FLAG | In the approval; the upload waits; they check the first points by eye |
| `COPY FAILED` / `COPY NEEDS A CHOICE` | Ask which match / check the card |
