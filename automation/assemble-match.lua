--[[
================================================================================
 Volleyball Autopilot scoreboard — assemble match footage
================================================================================

 Imports every clip from a folder and lays them end to end on a new timeline,
 gap-free, at the right frame rate.

 This exists because dragging twenty chapter files onto a timeline by hand is
 the one step where a silent mistake ruins everything downstream. A single
 one-frame gap shifts every event after it, and no offset can correct it —
 the overlay just drifts further behind the play as the match goes on, and you
 don't notice until the third set. A script appends deterministically.

 HOW TO RUN
   1. Copy the clips off the card into one folder (see CLIP_FOLDER below)
   2. Open Resolve with the project you want the timeline created in
   3. Workspace -> Console, then:
        dofile("C:/Users/YOURNAME/scoreboard-pipeline/assemble-match.lua")

 AFTER IT RUNS — one manual step left:
   Add a Fusion Composition to V2 and stretch it across the whole timeline.
   That's deliberately not scripted: Resolve's API can insert one but can't
   reliably place and resize it, and unlike a timeline gap, a Fusion clip that
   doesn't span is obvious — the overlay simply vanishes partway through.

 Then run build-scoreboard.lua and apply-match.lua as usual.
================================================================================
--]]

--------------------------------------------------------------------------------
-- CONFIG
--------------------------------------------------------------------------------

-- WHERE THE FOOTAGE LIVES
--
-- Keep one folder per match inside CLIP_ROOT, named by date:
--
--   E:\Volleyball Matches\
--       2026-08-09 vs Durham Attack\
--           DJI_0001.MP4
--           DJI_0002.MP4
--       2026-08-16 vs Riverside\
--           ...
--
-- Leave CLIP_FOLDER empty and the script uses the NEWEST subfolder, so the only
-- thing you do each match is make a dated folder and copy the card into it.
--
-- Per-match folders matter: the script imports EVERYTHING it finds, so a shared
-- dump would splice last week's game onto the end of this one.
--
-- Set CLIP_FOLDER to a full path to override.
local CLIP_ROOT   = [[E:\Volleyball Matches]]
-- prepare-match.py passes the exact folder (2026-09-28): the "newest folder"
-- fallback below can't see folder dates in Resolve's Lua and picks by NAME, so
-- "Thundercats 14U" would beat "2026-10-03 1415 vs Durham".
local CLIP_FOLDER = rawget(_G, "MATCH_CLIP_FOLDER") or ""

-- Where this script (and its siblings build-scoreboard.lua / apply-match.lua /
-- run-overlay.lua) live, and where the log file below gets written. One line
-- to change if you ever move the working folder.
local WORK_DIR = "C:/Users/YOURNAME/scoreboard-pipeline"

-- Timeline format. Must match what you shot.
--
-- Frame rate is locked by Resolve once any timeline exists in the project,
-- which is why this is set before anything is created.
--
-- Resolution matters more than it looks. CreateTimelineFromClips uses the
-- project's current settings, so a project defaulting to 1080p would scale your
-- 4K footage down without complaint. It also affects the overlay: everything in
-- the scoreboard is proportional EXCEPT the drop shadow, whose Softness is in
-- pixels — at 1080p it would read twice as heavy relative to the bar.
--
-- FRAME_RATE = "auto" (2026-09-27): read the rate off the first camera clip
-- and build the timeline at exactly that rate. The DJI's "60 fps" mode really
-- records 59.94 (60000/1001); an exact-60 timeline made Resolve repeat one
-- frame every ~16.7 s (a tiny hitch in fast pans). Matching the camera means
-- every camera frame lands on exactly one timeline frame. Falls back to
-- FRAME_RATE_FALLBACK if the clip's rate can't be read.
local FRAME_RATE  = "auto"
local FRAME_RATE_FALLBACK = "59.94"
local TIMELINE_W  = "3840"
local TIMELINE_H  = "2160"

-- Named after the MATCH date (2026-09-27, Kenny): taken from the first camera
-- file's name (DJI_YYYYMMDDhhmmss_...), else a date at the start of the match
-- folder's name, else today. Filled in below once the clips are found.
local TIMELINE_NAME = "Match " .. os.date("%Y-%m-%d")

local VIDEO_EXT = { mp4 = true, mov = true, mxf = true, braw = true }

--------------------------------------------------------------------------------
-- SETUP
--------------------------------------------------------------------------------

local log = {}
local function say(s) log[#log + 1] = tostring(s) print(tostring(s)) end

local function finish()
  local f = io.open(WORK_DIR .. "/assemble-log.txt", "w")
  if f then f:write(table.concat(log, "\n")) f:close() end
end

-- Reaching the Resolve API from the Console is fussier than the docs suggest.
-- Resolve() exists as a global function but returns nil here; what actually
-- works is the `resolve` userdata the Console already provides. Taking it via
-- rawget so a local declaration can't shadow the global before we've read it.
local resolve = rawget(_G, "resolve")
if not resolve and Resolve then
  pcall(function() resolve = Resolve() end)
end
if not resolve and bmd then
  pcall(function() resolve = bmd.scriptapp("Resolve") end)
end
if not resolve then
  say("ERROR: couldn't reach the Resolve API from here.")
  say("Run this from the Fusion Console inside Resolve.")
  finish()
  return
end

local pm      = resolve:GetProjectManager()
local project = pm and pm:GetCurrentProject()
if not project then
  say("ERROR: no project open.")
  finish()
  return
end

local mediaPool    = project:GetMediaPool()
local mediaStorage = resolve:GetMediaStorage()

--------------------------------------------------------------------------------
-- FIND THE CLIPS
--------------------------------------------------------------------------------

-- DJI's own chapter counter — the four digits just before the trailing _D —
-- survives renaming even when a converter changes everything else about the
-- filename. Shared by the pre-import sort and the post-import re-sort below.
local function chapterNum(path)
  local n = path:match("_(%d%d%d%d)_[A-Za-z]?%.[%w]+$")
           or path:match("_(%d%d%d%d)_")
  return n and tonumber(n) or nil
end

local function listClips(folder)
  local out = {}
  local items
  local ok = pcall(function() items = bmd.readdir(folder .. "\\*") end)
  if not ok or type(items) ~= "table" then return out end

  for _, it in ipairs(items) do
    if it and it.Name and it.IsDir ~= true then
      local ext = it.Name:match("%.([^.]+)$")
      if ext and VIDEO_EXT[ext:lower()] then
        out[#out + 1] = folder .. "\\" .. it.Name
      end
    end
  end

  -- Camera files only (2026-09-27): the YouTube export, the thumbnail source
  -- and any test renders are saved into this same match folder, so a re-run
  -- would otherwise splice our own exports onto the match. If the folder has
  -- DJI camera files, use only those.
  local cam = {}
  for _, p in ipairs(out) do
    if p:match("[^\\]+$"):match("^DJI_") then cam[#cam + 1] = p end
  end
  if #cam > 0 then out = cam end

  -- Sort by chapter number rather than plain filename — see chapterNum above.
  -- NOTE: this sort alone turned out not to be enough. AddItemListToMediaPool
  -- does not preserve the order clips are handed to it in; it was returning
  -- these two clips in the OPPOSITE order from what was passed in, most
  -- likely sorting internally by on-disk file creation time, which Shutter
  -- Encoder set to its own export time rather than the camera's recording
  -- time. So this sort keeps the printed report honest, but the order that
  -- actually matters is enforced again after import, below.
  table.sort(out, function(a, b)
    local na, nb = chapterNum(a), chapterNum(b)
    if na and nb and na ~= nb then return na < nb end
    return a < b
  end)
  return out
end

-- Newest subfolder of CLIP_ROOT, unless a folder was named explicitly.
local function newestSubfolder(root)
  local items
  local ok = pcall(function() items = bmd.readdir(root .. "\\*") end)
  if not ok or type(items) ~= "table" then return nil end

  local bestName, bestStamp
  for _, it in ipairs(items) do
    if it and it.Name and it.IsDir == true
       and it.Name ~= "." and it.Name ~= ".." then
      -- Date-prefixed names sort chronologically, so the name works as a
      -- fallback when LastWriteTime isn't exposed.
      local stamp = it.LastWriteTime or it.Name
      if bestStamp == nil or stamp > bestStamp then
        bestStamp, bestName = stamp, it.Name
      end
    end
  end
  if bestName then return root .. "\\" .. bestName end
end

if CLIP_FOLDER == "" then
  CLIP_FOLDER = newestSubfolder(CLIP_ROOT) or ""
end

local clips = (CLIP_FOLDER ~= "") and listClips(CLIP_FOLDER) or {}

say("=====================================================")
say(" Assembling match footage — " .. os.date("%Y-%m-%d %H:%M:%S"))
say(" Folder: " .. (CLIP_FOLDER ~= "" and CLIP_FOLDER or ("(none found under " .. CLIP_ROOT .. ")")))
say("")

if #clips == 0 then
  if CLIP_FOLDER == "" then
    say(" ERROR: no subfolders found in " .. CLIP_ROOT)
    say(" Make a dated folder there and copy the card into it.")
  else
    say(" ERROR: no video files in " .. CLIP_FOLDER)
  end
  say("=====================================================")
  finish()
  return
end

do
  local first = clips[1]:match("[^\\]+$") or ""
  local y, m, d = first:match("^DJI_(%d%d%d%d)(%d%d)(%d%d)")
  if not y then y, m, d = (CLIP_FOLDER:match("[^\\]+$") or ""):match("^(%d%d%d%d)%-(%d%d)%-(%d%d)") end
  if y then TIMELINE_NAME = string.format("Match %s-%s-%s", y, m, d) end
end

say(string.format(" Found %d clips, in this order:", #clips))
for i, p in ipairs(clips) do
  say(string.format("   %2d. %s", i, p:match("[^\\]+$")))
end

-- Sanity check the order itself, not just that something was found — this is
-- what would have caught chapter 0003 landing before chapter 0001.
local function chapterNumCheck(path)
  local n = path:match("_(%d%d%d%d)_[A-Za-z]?%.[%w]+$") or path:match("_(%d%d%d%d)_")
  return n and tonumber(n) or nil
end
local prevNum, outOfOrder = nil, false
for _, p in ipairs(clips) do
  local n = chapterNumCheck(p)
  if n and prevNum and n < prevNum then outOfOrder = true end
  if n then prevNum = n end
end
if outOfOrder then
  say(" *** Chapter numbers are NOT ascending — check the order above by hand")
  say(" before trusting this timeline. A renamed file can still break sorting")
  say(" if its chapter number itself got altered, not just its timestamp.")
end
say("")

--------------------------------------------------------------------------------
-- TIMELINE FORMAT — must be set before any timeline exists
-- (frame rate is set further down, right after import, because "auto" reads
-- it from the imported clips; importing media doesn't lock the rate)
--------------------------------------------------------------------------------

local curW = project:GetSetting("timelineResolutionWidth")
local curH = project:GetSetting("timelineResolutionHeight")
say(string.format(" Resolution: project is %sx%s, wanted %sx%s",
    tostring(curW), tostring(curH), TIMELINE_W, TIMELINE_H))

local okW = (tostring(curW) == TIMELINE_W) or
            project:SetSetting("timelineResolutionWidth", TIMELINE_W)
local okH = (tostring(curH) == TIMELINE_H) or
            project:SetSetting("timelineResolutionHeight", TIMELINE_H)

if okW and okH then
  say("   set to " .. TIMELINE_W .. "x" .. TIMELINE_H)
else
  say("   *** COULD NOT SET RESOLUTION ***")
  say("   Fix it by hand in Project Settings before continuing, or the 4K")
  say("   footage will be scaled to whatever the project is set to.")
end

--------------------------------------------------------------------------------
-- IMPORT AND APPEND
--------------------------------------------------------------------------------

local items
local okAdd = pcall(function()
  items = mediaStorage:AddItemListToMediaPool(clips)
end)

if not okAdd or type(items) ~= "table" or #items == 0 then
  say(" ERROR: couldn't import the clips into the Media Pool.")
  say("=====================================================")
  finish()
  return
end

say(string.format(" Imported %d of %d clips.", #items, #clips))
if #items ~= #clips then
  say(" *** Some clips didn't import — check formats before continuing. ***")
end

-- Frame rate: match the camera (see FRAME_RATE in CONFIG).
if FRAME_RATE == "auto" then
  local r = tonumber(items[1]:GetClipProperty("FPS"))
  if r and r > 0 then
    -- Normalise to the strings Resolve's timeline setting accepts.
    local known = { 23.976, 24, 25, 29.97, 30, 47.952, 48, 50, 59.94, 60, 95.904, 96, 100, 119.88, 120 }
    local best
    for _, k in ipairs(known) do
      if math.abs(k - r) < 0.02 then best = k end
    end
    FRAME_RATE = best and string.format("%g", best) or FRAME_RATE_FALLBACK
    say(string.format(" Camera frame rate: %s fps (from %s)", FRAME_RATE,
        tostring(items[1]:GetClipProperty("File Name"))))
  else
    FRAME_RATE = FRAME_RATE_FALLBACK
    say(" Camera frame rate unreadable — using " .. FRAME_RATE)
  end
  for _, it in ipairs(items) do
    local r2 = tonumber(it:GetClipProperty("FPS"))
    if r2 and math.abs(r2 - tonumber(FRAME_RATE)) > 0.02 then
      say(" *** " .. tostring(it:GetClipProperty("File Name")) .. " is " .. r2
          .. " fps, not " .. FRAME_RATE .. " — mixed camera settings? ***")
    end
  end
end

local currentRate = project:GetSetting("timelineFrameRate")
say(" Frame rate: project is " .. tostring(currentRate) ..
    ", wanted " .. FRAME_RATE)

if math.abs((tonumber(currentRate) or 0) - tonumber(FRAME_RATE)) > 0.001 then
  if project:SetSetting("timelineFrameRate", FRAME_RATE) then
    say("   changed to " .. FRAME_RATE)
  else
    say("   *** COULD NOT CHANGE IT ***")
    say("   Resolve locks the frame rate once any timeline exists in the")
    say("   project. Either delete the existing timelines, or start a new")
    say("   project and run this again. Carrying on would give you footage")
    say("   conformed to the wrong rate.")
    say("=====================================================")
    finish()
    return
  end
end

-- AddItemListToMediaPool does NOT reliably return items in the order they
-- were passed in — confirmed by direct test: handed [chapter 1, chapter 3],
-- it came back [chapter 3, chapter 1]. It appears to sort by on-disk file
-- creation time, which a converter can set to its own export time rather
-- than the camera's recording time. CreateTimelineFromClips then places
-- clips in whatever order its input array is in, so THIS is the order that
-- actually decides the edit — re-enforce it here, right before building the
-- timeline, rather than trusting the import order at all.
table.sort(items, function(a, b)
  local na = chapterNum(a:GetClipProperty("File Name") or a:GetName() or "")
  local nb = chapterNum(b:GetClipProperty("File Name") or b:GetName() or "")
  if na and nb and na ~= nb then return na < nb end
  return (a:GetName() or "") < (b:GetName() or "")
end)

say(" Timeline order (after re-sorting by chapter number):")
for i, it in ipairs(items) do
  say(string.format("   %2d. %s", i, tostring(it:GetClipProperty("File Name") or it:GetName())))
end

-- Sum the source durations so we can prove the timeline has no gaps. Done in
-- SECONDS rather than raw frame counts: these clips reported FPS 59.94, not
-- an exact 60, so a straight frame-count sum against a 60fps timeline always
-- comes up short by design — that's the timeline correctly stretching 59.94
-- fps footage onto a 60.000 fps grid, not a missing gap. Converting through
-- seconds removes that false alarm while still catching a REAL gap.
local timelineRate = tonumber(FRAME_RATE) or 60
local expectedFrames = 0
for _, it in ipairs(items) do
  local srcFrames = tonumber(it:GetClipProperty("Frames")) or 0
  local srcFps     = tonumber(it:GetClipProperty("FPS")) or timelineRate
  expectedFrames = expectedFrames + math.floor(srcFrames / srcFps * timelineRate + 0.5)
end

local timeline
local okTl = pcall(function()
  timeline = mediaPool:CreateTimelineFromClips(TIMELINE_NAME, items)
end)

if not okTl or not timeline then
  say(" ERROR: couldn't create the timeline.")
  say("=====================================================")
  finish()
  return
end

project:SetCurrentTimeline(timeline)

--------------------------------------------------------------------------------
-- VERIFY — this is the whole point of the script
--------------------------------------------------------------------------------

local startF = tonumber(timeline:GetStartFrame()) or 0
local endF   = tonumber(timeline:GetEndFrame()) or 0
local actualFrames = endF - startF

say("")
say(" Timeline: " .. TIMELINE_NAME)
say(string.format(" Expected %d frames from the source clips", expectedFrames))
say(string.format(" Timeline is %d frames", actualFrames))

-- A frame or two either way is rounding noise from converting each clip's
-- own frame rate to the timeline's (e.g. 59.94 -> 60), not a real gap.
-- Anything bigger is worth stopping for.
local drift = actualFrames - expectedFrames
if math.abs(drift) <= 2 then
  say(" No gaps. Total length matches the footage (within rounding).")
else
  say(string.format(" *** MISMATCH: %+d frames ***", drift))
  say(" The timeline doesn't match the sum of the clips, which means a gap or")
  say(" an overlap. Do not use this for a match — the overlay will drift.")
end

local rate = tonumber(FRAME_RATE) or 30
say(string.format(" Duration: %.1f minutes", actualFrames / rate / 60))

-- Read the format back off the finished timeline rather than trusting that the
-- project settings took. A timeline can carry its own overrides.
local tlRate = timeline:GetSetting("timelineFrameRate")
local tlW    = timeline:GetSetting("timelineResolutionWidth")
local tlH    = timeline:GetSetting("timelineResolutionHeight")
say("")
say(string.format(" Timeline format: %sx%s @ %s fps",
    tostring(tlW), tostring(tlH), tostring(tlRate)))

local formatOK = (tostring(tlW) == TIMELINE_W)
             and (tostring(tlH) == TIMELINE_H)
             and math.abs((tonumber(tlRate) or 0) - tonumber(FRAME_RATE)) < 0.001

if formatOK then
  say(" Matches what you shot.")
else
  say(string.format(" *** NOT WHAT WAS ASKED FOR (%sx%s @ %s) ***",
      TIMELINE_W, TIMELINE_H, FRAME_RATE))
  say(" Check Project Settings before adding the overlay — the scoreboard")
  say(" scales proportionally, but the drop shadow is measured in pixels and")
  say(" will look wrong at another resolution.")
end

-- Playback frame rate is a separate project setting that defaults to 24 and
-- can't be changed from a script (SetSetting refuses it), so flag it loudly.
local pbRate = project:GetSetting("timelinePlaybackFrameRate")
if math.abs((tonumber(pbRate) or 0) - tonumber(FRAME_RATE)) < 0.001 then
  say(" Playback frame rate: " .. tostring(pbRate) .. " (OK)")
else
  say("")
  say(string.format(" *** PLAYBACK FRAME RATE IS %s, NOT %s ***", tostring(pbRate), FRAME_RATE))
  say(" Preview will play in slow motion (exports are fine). Fix it now:")
  say(" Project Settings (Shift+9) -> Master Settings -> Playback frame rate -> "
      .. FRAME_RATE .. " -> Save")
end

say("")
say(" NEXT:")
say("   1. Add a Fusion Composition to V2, stretched across the whole timeline")
say("   2. Open it on the Fusion page")
say("   3. dofile(\"" .. WORK_DIR .. "/build-scoreboard.lua\")")
say("   4. dofile(\"" .. WORK_DIR .. "/apply-match.lua\")")
say("=====================================================")

finish()
