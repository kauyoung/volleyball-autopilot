--[[
================================================================================
 Venom Rebels scoreboard — apply match data
================================================================================

 Reads a match JSON file and writes keyframes onto the scoreboard nodes built by
 build-scoreboard.lua:

   Team1Score / Team2Score   StyledText   every point
   Team1Sets  / Team2Sets    StyledText   at set end
   SetNumber                 StyledText   "SET 1" -> "SET 2" -> "SET 3"
   Team1ServeMerge.Blend     0 <-> 1      when serve changes
   Team2ServeMerge.Blend     0 <-> 1      when serve changes

 HOW TO RUN
   1. Open the Fusion Composition on the Fusion page.
   2. Workspace -> Console (so you can see the report).
   3. Workspace -> Scripts -> Comp -> apply-match

 BEFORE YOU RUN
   Set CLEAR_EXISTING = false in build-scoreboard.lua. Re-running the builder
   after this script deletes every keyframe it wrote.

 All values are held as STEP keyframes — a score must snap from 14 to 15, never
 tween through 14.5.
================================================================================
--]]

--------------------------------------------------------------------------------
-- CONFIG
--------------------------------------------------------------------------------

-- WHERE THE MATCH FILE LIVES
--
-- Normally leave MATCH_FILE empty. The script looks for the newest .json in
-- two places, in order:
--
--   1. The newest match folder under MATCH_ROOT — i.e. alongside the footage,
--      which is the tidiest place for it
--   2. MATCH_FALLBACK, the working folder
--
-- So the routine after a game is: export from the phone, drop the .json into
-- the same folder you copied the card into, run this.
--
-- It prints the file it chose and the team names, so if it grabs the wrong one
-- you'll see it immediately rather than wondering why the scores look odd.
-- Set MATCH_FILE to a full path to override the search entirely.
local MATCH_ROOT     = [[E:\Venom Matches]]

-- Where this script (and its siblings assemble-match.lua / build-scoreboard.lua /
-- run-overlay.lua) live. Doubles as the fallback search location for the match
-- JSON, and where the log file below gets written. One line to change if you
-- ever move the working folder.
local WORK_DIR       = "C:/Users/YOURNAME/scoreboard-pipeline"
local MATCH_FALLBACK = WORK_DIR
local MATCH_FILE     = rawget(_G, "SCOREBOARD_MATCH_FILE") or ""   -- global = testing override

-- Frame in the COMP that corresponds to t = 0 in the match data (i.e. the first
-- frame of your video). If the Fusion Composition starts at the same point on
-- the timeline as the footage, leave this at 0.
local COMP_START_FRAME = 0

-- Extra seconds to shift every event. Use the scorekeeper's own offset field
-- first; this is a second-chance nudge if the overlay drifts from the play.
local EXTRA_OFFSET_SEC = 0.0

-- AUTO SET ALIGNMENT (added 2026-09-25)
-- Each set break is a camera stop, so each set after the first starts at a
-- clip join on V1. If Stop Recording / Resume Recording was tapped early or
-- late, every score in that set is off by the same amount. With this on, each
-- set's scores are shifted as a block so its 0-0 lands exactly on its clip
-- join. Only applied when the number of joins matches the number of set breaks
-- (i.e. the camera was only stopped between sets) and no shift is bigger than
-- ALIGN_MAX_SEC. The match file itself is never modified.
local AUTO_ALIGN_SETS = true
local ALIGN_MAX_SEC   = 20

local CLEAR_FIRST = true   -- remove existing keyframes before writing new ones

-- Frames per second. Leave at 0 — the script reads the real rate from the
-- composition. Only set a number here to deliberately override it.
local FPS_OVERRIDE = 0

--------------------------------------------------------------------------------
-- SETUP
--------------------------------------------------------------------------------

local comp = comp or (fusion and fusion:GetCurrentComp())
if not comp then
  print("ERROR: no composition. Open the Fusion page on your scoreboard comp.")
  return
end

local problems = {}
local function fail(msg) problems[#problems + 1] = msg end

--------------------------------------------------------------------------------
-- MINIMAL JSON READER
-- Resolve's Lua has no JSON library, so this parses the subset we emit:
-- objects, arrays, strings, numbers, true/false/null. No unicode escapes.
--------------------------------------------------------------------------------

local function parseJSON(str)
  local pos = 1

  local function skip()
    while pos <= #str and str:sub(pos, pos):match("[ \t\r\n]") do pos = pos + 1 end
  end

  local parseValue

  local function parseString()
    pos = pos + 1                        -- opening quote
    local out = {}
    while pos <= #str do
      local c = str:sub(pos, pos)
      if c == '"' then pos = pos + 1 return table.concat(out) end
      if c == "\\" then
        local n = str:sub(pos + 1, pos + 1)
        local map = { n = "\n", t = "\t", r = "\r", b = "\b", f = "\f" }
        out[#out + 1] = map[n] or n
        pos = pos + 2
      else
        out[#out + 1] = c
        pos = pos + 1
      end
    end
    error("unterminated string")
  end

  local function parseNumber()
    local s, e = str:find("^-?%d+%.?%d*[eE]?[-+]?%d*", pos)
    local num = tonumber(str:sub(s, e))
    pos = e + 1
    return num
  end

  local function parseArray()
    pos = pos + 1
    local arr = {}
    skip()
    if str:sub(pos, pos) == "]" then pos = pos + 1 return arr end
    while true do
      arr[#arr + 1] = parseValue()
      skip()
      local c = str:sub(pos, pos)
      pos = pos + 1
      if c == "]" then return arr end
      if c ~= "," then error("expected , or ] at " .. pos) end
      skip()
    end
  end

  local function parseObject()
    pos = pos + 1
    local obj = {}
    skip()
    if str:sub(pos, pos) == "}" then pos = pos + 1 return obj end
    while true do
      skip()
      local key = parseString()
      skip()
      pos = pos + 1                      -- colon
      obj[key] = parseValue()
      skip()
      local c = str:sub(pos, pos)
      pos = pos + 1
      if c == "}" then return obj end
      if c ~= "," then error("expected , or } at " .. pos) end
    end
  end

  parseValue = function()
    skip()
    local c = str:sub(pos, pos)
    if c == "{" then return parseObject() end
    if c == "[" then return parseArray() end
    if c == '"' then return parseString() end
    if str:sub(pos, pos + 3) == "true"  then pos = pos + 4 return true end
    if str:sub(pos, pos + 4) == "false" then pos = pos + 5 return false end
    if str:sub(pos, pos + 3) == "null"  then pos = pos + 4 return nil end
    return parseNumber()
  end

  return parseValue()
end

--------------------------------------------------------------------------------
-- LOAD THE MATCH
--------------------------------------------------------------------------------

-- Find the newest .json in MATCH_FOLDER unless a file was named explicitly.
local function newestMatchFile(folder)
  local items
  local ok = pcall(function() items = bmd.readdir(folder .. "\\*.json") end)
  if not ok or type(items) ~= "table" then return nil end

  local bestName, bestTime
  for _, it in ipairs(items) do
    if it and it.Name and it.IsDir ~= true then
      -- LastWriteTime isn't guaranteed across versions; fall back to the name,
      -- which works because exports are prefixed with the ISO date.
      local stamp = it.LastWriteTime or it.Name
      if bestTime == nil or stamp > bestTime then
        bestTime, bestName = stamp, it.Name
      end
    end
  end
  if bestName then return folder .. "\\" .. bestName end
end

-- Newest dated subfolder of the match root, so the export can sit with the
-- footage it belongs to.
local function newestSubfolder(root)
  local items
  local ok = pcall(function() items = bmd.readdir(root .. "\\*") end)
  if not ok or type(items) ~= "table" then return nil end

  local bestName, bestStamp
  for _, it in ipairs(items) do
    if it and it.Name and it.IsDir == true
       and it.Name ~= "." and it.Name ~= ".." then
      local stamp = it.LastWriteTime or it.Name
      if bestStamp == nil or stamp > bestStamp then
        bestStamp, bestName = stamp, it.Name
      end
    end
  end
  if bestName then return root .. "\\" .. bestName end
end

if MATCH_FILE == "" then
  local matchFolder = newestSubfolder(MATCH_ROOT)
  if matchFolder then
    MATCH_FILE = newestMatchFile(matchFolder) or ""
  end
  if MATCH_FILE == "" then
    MATCH_FILE = newestMatchFile(MATCH_FALLBACK) or ""
  end
  if MATCH_FILE == "" then
    print("ERROR: no .json found in either:")
    print("  " .. tostring(matchFolder or (MATCH_ROOT .. " (no subfolders)")))
    print("  " .. MATCH_FALLBACK)
    print("Save your export in one of those, or set MATCH_FILE to a full path.")
    return
  end
end

local fh = io.open(MATCH_FILE, "r")
if not fh then
  print("ERROR: can't open match file:")
  print("  " .. MATCH_FILE)
  print("Check MATCH_ROOT / MATCH_FALLBACK / MATCH_FILE at the top of this script.")
  return
end

print("Match file: " .. MATCH_FILE)
local raw = fh:read("*a")
fh:close()

local ok, match = pcall(parseJSON, raw)
if not ok or type(match) ~= "table" or not match.events then
  print("ERROR: couldn't parse the match file — " .. tostring(match))
  return
end

--------------------------------------------------------------------------------
-- FRAME RATE
-- Event times in the match file are in SECONDS, which is deliberately frame-rate
-- agnostic — the same file has to work whether the footage was shot at 24, 30 or
-- 60 fps. The conversion to frames must therefore use the COMPOSITION's rate,
-- never a number baked into the file.
--
-- Trusting the file is what went wrong first time round: the JSON said 30, the
-- comp ran at 24, and every event landed 25% too late. Nothing errored — the
-- overlay just drifted further behind the play with every point, which over a
-- full match means the score updates minutes after the rally.
--------------------------------------------------------------------------------

local compFps
pcall(function() compFps = tonumber(comp:GetPrefs("Comp.FrameFormat.Rate")) end)

local fps, fpsSource
if FPS_OVERRIDE and FPS_OVERRIDE > 0 then
  fps, fpsSource = FPS_OVERRIDE, "FPS_OVERRIDE in this script"
elseif compFps and compFps > 0 then
  fps, fpsSource = compFps, "the composition"
else
  fps, fpsSource = (match.fps or 30), "the match file (couldn't read the comp)"
  fail("Couldn't read the composition's frame rate — fell back to the match "
    .. "file's value. Check timing before trusting the render.")
end

local baseOffset = (match.offset or 0) + EXTRA_OFFSET_SEC

if match.fps and math.abs(match.fps - fps) > 0.01 then
  fail(string.format("Match file says %g fps but the comp is %g fps. Using the "
    .. "comp — the file's value is ignored on purpose.", match.fps, fps))
end

print(string.format("Loaded %d events: %s vs %s", #match.events,
      tostring(match.team1), tostring(match.team2)))
print(string.format("Frame rate: %g fps (from %s)", fps, fpsSource))

--------------------------------------------------------------------------------
-- AUTO SET ALIGNMENT — see AUTO_ALIGN_SETS in CONFIG
--------------------------------------------------------------------------------

local alignNotes = {}
local function alignSetsToClipJoins()
  -- 2026-10-26: camera-time.py already put every point on the camera timeline from the
  -- scorekeeper's clock times (handles camera stops in and between sets) - nothing to align
  if match.timeBase == "camera" then
    alignNotes[#alignNotes + 1] = "skipped — points already placed on the camera timeline from clock times (camera-time.py)"
    return
  end
  -- Clip joins on V1, in seconds from the first clip.
  local r = rawget(_G, "resolve")
  if not r and Resolve then pcall(function() r = Resolve() end) end
  if not r and bmd then pcall(function() r = bmd.scriptapp("Resolve") end) end
  local proj = r and r:GetProjectManager():GetCurrentProject()
  local tl = proj and proj:GetCurrentTimeline()
  if not tl then alignNotes[#alignNotes + 1] = "skipped — couldn't read the timeline" return end
  local items = tl:GetItemListInTrack("video", 1) or {}
  local clips = {}
  for _, it in ipairs(items) do
    local name = ""
    pcall(function() name = it:GetMediaPoolItem():GetClipProperty("File Name") or "" end)
    if name == "" then name = it:GetName() or "" end
    clips[#clips + 1] = { start = it:GetStart(), dur = it:GetDuration(), name = name }
  end
  table.sort(clips, function(a, b) return a.start < b.start end)
  if #clips < 2 then alignNotes[#alignNotes + 1] = "skipped — only one clip, no set breaks to align" return end
  local tlFps = tonumber(tl:GetSetting("timelineFrameRate")) or fps

  -- Only REAL camera stops count as set breaks. When the camera keeps rolling
  -- through a long match it still splits the recording into chapter files, and
  -- those joins are seamless — treating them as set breaks would shift sets onto
  -- the wrong joins. DJI file names carry the recording start time
  -- (DJI_YYYYMMDDHHMMSS_NNNN_D); if the next clip starts within a few seconds of
  -- where this one ended, it's a chapter split, not a stop. Unparseable names
  -- are treated as real stops (the previous behaviour).
  local function startSecs(name)
    local Y, Mo, D, h, mi, s = name:match("(%d%d%d%d)(%d%d)(%d%d)(%d%d)(%d%d)(%d%d)")
    if not Y then return nil end
    return os.time({ year = tonumber(Y), month = tonumber(Mo), day = tonumber(D),
                     hour = tonumber(h), min = tonumber(mi), sec = tonumber(s) })
  end
  local joins, splits = {}, 0
  for i = 2, #clips do
    local a, b = startSecs(clips[i - 1].name), startSecs(clips[i].name)
    local seamless = a and b and math.abs((b - a) - clips[i - 1].dur / tlFps) <= 3
    if seamless then
      splits = splits + 1
    else
      joins[#joins + 1] = (clips[i].start - clips[1].start) / tlFps
    end
  end
  if splits > 0 then
    alignNotes[#alignNotes + 1] = string.format("ignored %d seamless chapter split(s) — not set breaks", splits)
  end
  if #joins == 0 then
    alignNotes[#alignNotes + 1] = "no camera stops found (recorded straight through) — sets kept as scored"
    return
  end

  -- Where each set after the first begins in the data (its 0-0 event).
  local setStart, order = {}, {}
  for _, e in ipairs(match.events) do
    if e.set and e.set > 1 and not setStart[e.set] then
      setStart[e.set] = e.t
      order[#order + 1] = e.set
    end
  end
  if #order == 0 then alignNotes[#alignNotes + 1] = "skipped — the match data has only one set" return end
  if #order ~= #joins then
    alignNotes[#alignNotes + 1] = string.format(
      "skipped — %d set break(s) in the data but %d clip join(s) in the footage. "
      .. "The camera was probably stopped mid-set; align by hand if needed.", #order, #joins)
    fail(alignNotes[#alignNotes])
    return
  end

  local shift = {}
  for i, s in ipairs(order) do
    local d = joins[i] - (setStart[s] + baseOffset)
    if math.abs(d) > ALIGN_MAX_SEC then
      alignNotes[#alignNotes + 1] = string.format(
        "skipped — set %d would move %.1f s, more than ALIGN_MAX_SEC (%d s). Check the data.", s, d, ALIGN_MAX_SEC)
      fail(alignNotes[#alignNotes])
      return
    end
    shift[s] = d
  end
  for _, e in ipairs(match.events) do
    if shift[e.set] then e.t = e.t + shift[e.set] end
  end
  for _, s in ipairs(order) do
    alignNotes[#alignNotes + 1] = string.format("set %d moved %s%.2f s to start on its clip join",
      s, shift[s] >= 0 and "+" or "", shift[s])
  end
end

if AUTO_ALIGN_SETS then
  local ok, err = pcall(alignSetsToClipJoins)
  if not ok then alignNotes[#alignNotes + 1] = "skipped — " .. tostring(err) end
  for _, n in ipairs(alignNotes) do print("Set alignment: " .. n) end
end

--------------------------------------------------------------------------------
-- KEYFRAME HELPERS
--------------------------------------------------------------------------------

local function frameOf(t)
  return math.floor((t + baseOffset) * fps + 0.5) + COMP_START_FRAME
end

local function tool(name)
  local t = comp:FindTool(name)
  if not t then fail("node not found: " .. name) end
  return t
end

-- Write a series of {frame, value} pairs onto one input as STEP keyframes.
-- Consecutive duplicates are skipped, so a score that doesn't change doesn't
-- get a redundant key.
local function animate(node, inputName, series, label, stepHold)
  if not node then return 0 end

  -- Clear any spline left by a previous run.
  if CLEAR_FIRST then
    pcall(function()
      local out = node[inputName]:GetConnectedOutput()
      if out then out:GetTool():Delete() end
    end)
  end

  -- Attach a spline BEFORE writing anything. This is the fix for the scoreboard
  -- that froze on the final score: on an un-animated input, node[input][frame]
  -- does not create a keyframe, it just overwrites the one static value. So all
  -- 125 writes landed on the same slot and the last one won. Confirmed by
  -- diagnostic: a numeric input written at frames 0 and 200 read back as the
  -- same value at both, and only sprouted a spline once AddModifier was called.
  local attached = false
  pcall(function()
    attached = node:AddModifier(inputName, "BezierSpline") and true or false
  end)
  if not attached then
    fail(string.format("%s: couldn't attach a spline to %s — values will not "
      .. "change over time.", label, inputName))
  end

  local written, last = 0, nil
  for _, kv in ipairs(series) do
    local f, v = kv[1], kv[2]
    if v ~= last then
      -- Hold the previous value until one frame before the change, so the value
      -- snaps rather than ramping. Scores must never read 14.5.
      if stepHold and last ~= nil and f > 0 then
        pcall(function() node[inputName][f - 1] = last end)
      end
      local okSet = pcall(function() node[inputName][f] = v end)
      if not okSet then
        fail(string.format("%s: couldn't write %s at frame %d", label, inputName, f))
        return written
      end
      written = written + 1
      last = v
    end
  end
  return written
end

-- Sample an input across the match and report how many distinct values appear.
-- Deliberately more than two samples: the serve Blend only ever holds 0 or 1, so
-- checking just the start and midpoint reported "STILL STATIC" whenever those
-- two moments happened to share a value — a false alarm on a working setup.
local function verify(nodeName, inputName, fFirst, fLast, staticOK)
  local n = comp:FindTool(nodeName)
  if not n then return "node missing" end

  local seen, order = {}, {}
  local SAMPLES = 9
  for i = 0, SAMPLES - 1 do
    local f = math.floor(fFirst + (fLast - fFirst) * i / (SAMPLES - 1))
    local v
    pcall(function() v = n[inputName][f] end)
    v = tostring(v)
    if not seen[v] then seen[v] = true order[#order + 1] = v end
  end

  return string.format("%d distinct across %d samples [%s] %s",
    #order, SAMPLES, table.concat(order, " "),
    (#order > 1) and "OK" or (staticOK and "OK (no sets won, stays 0)" or "*** STILL STATIC ***"))
end

--------------------------------------------------------------------------------
-- BUILD THE SERIES
--------------------------------------------------------------------------------

local sc1, sc2, st1, st2, setNo, srv1, srv2 = {}, {}, {}, {}, {}, {}, {}

-- 2026-10-25 (Kenny: both serve balls showing at the end of Play Off set 1): several
-- events on the SAME frame (scorekeeper double taps, set start + first points, a camera
-- gap) made animate() write its "hold" key at f-1 more than once - the second write
-- overwrote the first with the wrong value and the Blend spline then RAMPED the other
-- team's ball in across the whole set break. Only the last event on a frame counts now.
local seriesPrevF = nil
for _, e in ipairs(match.events) do
  local f = frameOf(e.t)
  local i = (f == seriesPrevF) and #sc1 or (#sc1 + 1)
  sc1[i]   = { f, tostring(e.score1) }
  sc2[i]   = { f, tostring(e.score2) }
  st1[i]   = { f, tostring(e.sets1) }
  st2[i]   = { f, tostring(e.sets2) }
  setNo[i] = { f, "SET " .. tostring(e.set) }
  srv1[i]  = { f, (e.serve == 1) and 1 or 0 }
  srv2[i]  = { f, (e.serve == 2) and 1 or 0 }
  seriesPrevF = f
end

--------------------------------------------------------------------------------
-- APPLY
--------------------------------------------------------------------------------

comp:Lock()
comp:StartUndo("Apply match data")

local counts = {}
-- stepHold on EVERYTHING. Fusion resolves a spline to the NEAREST key, not the
-- previous one, so with keys at frame 0 ("0") and frame 1254 ("1") the value
-- flipped at frame 627 — halfway — and the opponent's set count read 1 before
-- they'd won a set. Writing the outgoing value again at f-1 pins each change to
-- its own frame instead of drifting to the midpoint.
counts["Team1Score"] = animate(tool("Team1Score"), "StyledText", sc1, "Team1Score", true)
counts["Team2Score"] = animate(tool("Team2Score"), "StyledText", sc2, "Team2Score", true)
counts["Team1Sets"]  = animate(tool("Team1Sets"),  "StyledText", st1, "Team1Sets", true)
counts["Team2Sets"]  = animate(tool("Team2Sets"),  "StyledText", st2, "Team2Sets", true)
counts["SetNumber"]  = animate(tool("SetNumber"),  "StyledText", setNo, "SetNumber", true)
-- stepHold = true: Blend is numeric, so without a held key it would ramp the
-- serve ball in and out rather than switching it.
counts["Team1Serve"] = animate(tool("Team1ServeMerge"), "Blend", srv1, "Team1ServeMerge", true)
counts["Team2Serve"] = animate(tool("Team2ServeMerge"), "Blend", srv2, "Team2ServeMerge", true)

--------------------------------------------------------------------------------
-- SET POINT / MATCH POINT TAGS (2026-09-26)
-- After every event, a team has SET POINT if winning the next rally wins the
-- set: (score+1) reaches the target (25 or 15 per format; 15 in a 3rd set) with a 2-point lead.
-- It's MATCH POINT if that set would also be their 2nd set. Worked out fresh
-- at every point, so deuce behaves naturally: 24-23 SET POINT -> 24-24 gone ->
-- 25-24 SET POINT again (for whoever leads). Nothing shows once the set is won
-- or at 0-0. Rules match the scorekeeper's setTarget() (best of 3, set 3 to 15).
--------------------------------------------------------------------------------
local SETS_TO_WIN = 2
-- Match format (2026-09-28, scorekeeper "format"): best-of-3 = set 3 to 15 and
-- MATCH POINT tags; formats where every set is played (2 sets / 3 sets, all to
-- 25) only ever show SET POINT. Old match files without a format = best-of-3.
local FMT = type(match.format) == "table" and match.format or {}
local FMT_BEST = (FMT.mode or "best") == "best"
local FMT_DECIDER = tonumber(FMT.decider) or 15
-- 2026-10-02: sets can be to 15 (12U / 4 v 4) — "pts"; old files = 25
local FMT_PTS = tonumber(FMT.pts) or 25
local function setTarget(setNo) return (FMT_BEST and setNo >= 3) and FMT_DECIDER or FMT_PTS end

local tagOn  = { {}, {} }
local tagTxt = { {}, {} }
local tagMoments = 0
for _, e in ipairs(match.events) do
  local f = frameOf(e.t)
  local sc   = { tonumber(e.score1) or 0, tonumber(e.score2) or 0 }
  local sets = { tonumber(e.sets1) or 0,  tonumber(e.sets2) or 0 }
  local target = setTarget(tonumber(e.set) or 1)
  local hi, lo = math.max(sc[1], sc[2]), math.min(sc[1], sc[2])
  local setOver = hi >= target and (hi - lo) >= 2
  for t = 1, 2 do
    local me, them = sc[t], sc[3 - t]
    local sp = (not setOver) and (me + 1 >= target) and ((me + 1) - them >= 2)
    -- sets[t] is sets already won; if this set is won too, is that the match?
    local mp = sp and FMT_BEST and (sets[t] + 1 >= SETS_TO_WIN)
    tagOn[t][#tagOn[t] + 1] = { f, sp and 1 or 0 }
    if sp then
      tagTxt[t][#tagTxt[t] + 1] = { f, mp and "MATCH POINT" or "SET POINT" }
      tagMoments = tagMoments + 1
    end
  end
end

--------------------------------------------------------------------------------
-- YOUTUBE INFO (2026-09-27)
-- Writes youtube-info.json next to this script: video times (seconds, as the
-- scoreboard shows them — set alignment included) of each set start and the
-- first MATCH POINT, plus the final score of each set. prep-upload.py turns it
-- into the title / description / chapters while the export is still rendering.
-- Doesn't touch the scoreboard.
--------------------------------------------------------------------------------
pcall(function()
  local setStart, setFinal, order = {}, {}, {}
  local firstMP
  local evs = {}   -- every point as the scoreboard shows it (for the review sheet)
  for _, e in ipairs(match.events) do
    local s = tonumber(e.set) or 1
    local sec = (frameOf(e.t) - COMP_START_FRAME) / fps
    if not setStart[s] then setStart[s] = sec order[#order + 1] = s end
    setFinal[s] = { tonumber(e.score1) or 0, tonumber(e.score2) or 0 }
    evs[#evs + 1] = string.format("[%.3f,%d,%d,%d,%d,%d]", sec, s, tonumber(e.score1) or 0,
      tonumber(e.score2) or 0, tonumber(e.sets1) or 0, tonumber(e.sets2) or 0)
  end
  for t = 1, 2 do
    for _, kv in ipairs(tagTxt[t]) do
      if kv[2] == "MATCH POINT" then
        local sec = (kv[1] - COMP_START_FRAME) / fps
        if not firstMP or sec < firstMP then firstMP = sec end
        break
      end
    end
  end
  local parts = {}
  for _, s in ipairs(order) do
    parts[#parts + 1] = string.format('{"set":%d,"start":%.3f,"score1":%d,"score2":%d}',
      s, (s == order[1]) and 0 or setStart[s], setFinal[s][1], setFinal[s][2])
  end
  local function esc(x) return (tostring(x or ""):gsub('\\', '\\\\'):gsub('"', '\\"')) end
  -- video length: from the match timeline (reliable), else the comp's range
  local endSec
  pcall(function()
    local rv = rawget(_G, "resolve") or Resolve()
    local mtl = rv:GetProjectManager():GetCurrentProject():GetCurrentTimeline()
    endSec = (mtl:GetEndFrame() - mtl:GetStartFrame()) / tonumber(mtl:GetSetting("timelineFrameRate"))
  end)
  if not endSec then
    local ca = comp:GetAttrs()
    endSec = ((ca.COMPN_RenderEnd or ca.COMPN_GlobalEnd or 0) - COMP_START_FRAME + 1) / fps
  end
  -- 2026-10-02: final result from the scorekeeper (2-sets-only formats: a 1-1
  -- match is won on total points). Older files have none -> null.
  local resultJson = "null"
  local R = match.result
  if type(R) == "table" then
    resultJson = string.format('{"winner":%d,"decidedBy":"%s","sets1":%d,"sets2":%d,"points1":%d,"points2":%d}',
      tonumber(R.winner) or 0, esc(tostring(R.decidedBy or "")), tonumber(R.sets1) or 0, tonumber(R.sets2) or 0,
      tonumber(R.points1) or 0, tonumber(R.points2) or 0)
  end
  local forced = {}
  for _, s in ipairs(type(match.forcedSets) == "table" and match.forcedSets or {}) do forced[#forced + 1] = tostring(tonumber(s) or 0) end
  local json = string.format('{"team1":"%s","team2":"%s","date":"%s","matchFile":"%s","fps":%.5f,"end":%.3f,"format":{"code":"%s","mode":"%s","pts":%d,"decider":%d},"result":%s,"forcedSets":[%s],"sets":[%s],"firstMatchPoint":%s,"events":[%s]}',
    esc(match.team1), esc(match.team2), esc(match.date), esc(MATCH_FILE), fps, endSec,
    esc(FMT.code or "bo3"), esc(FMT.mode or "best"), FMT_PTS, FMT_DECIDER, resultJson, table.concat(forced, ","),
    table.concat(parts, ","), firstMP and string.format("%.3f", firstMP) or "null",
    table.concat(evs, ","))
  local f = io.open(WORK_DIR .. "/youtube-info.json", "w")
  if f then f:write(json) f:close() end
end)

--------------------------------------------------------------------------------
-- KEY WRITER FOR FADES (2026-09-27)
-- Writes an explicit list of {frame, value} keys onto a numeric input (fresh
-- spline each run). Callers always put a key on BOTH ends of every flat
-- stretch, so Fusion's smooth splines stay perfectly flat between fades.
--------------------------------------------------------------------------------
local function writeKeys(node, inputName, list, label)
  if not node then return 0 end
  pcall(function()
    local o = node[inputName]:GetConnectedOutput()
    if o then o:GetTool():Delete() end
  end)
  local ok = pcall(function() node:AddModifier(inputName, "BezierSpline") end)
  if not ok then fail((label or inputName) .. ": couldn't attach a spline") return 0 end
  table.sort(list, function(a, b) return a[1] < b[1] end)
  local n, lastF = 0, nil
  for _, kv in ipairs(list) do
    if kv[1] ~= lastF and kv[1] >= 0 then
      pcall(function() node[inputName][kv[1]] = kv[2] end)
      n, lastF = n + 1, kv[1]
    end
  end
  return n
end

-- On/off series -> fade keys. Each change starts fading AT the point and is
-- complete fadeFrames later (shortened if the next change comes sooner).
local TAG_FADE_SEC = 0.25
local function fadeKeys(series, fadeFrames)
  local changes, last = {}, nil
  for _, kv in ipairs(series) do
    if kv[2] ~= last then changes[#changes + 1] = { kv[1], kv[2], last } last = kv[2] end
  end
  local keys = {}
  if #changes == 0 then return { { 0, 0 } } end
  keys[#keys + 1] = { 0, changes[1][3] or changes[1][2] }
  for i, c in ipairs(changes) do
    local f, to, from = c[1], c[2], c[3]
    if from == nil then
      keys[#keys + 1] = { f, to }
    else
      local nextF = changes[i + 1] and changes[i + 1][1] or math.huge
      local F = math.max(1, math.min(fadeFrames, nextF - f - 4))
      keys[#keys + 1] = { f - 1, from }
      keys[#keys + 1] = { f, from }
      keys[#keys + 1] = { f + F, to }
      keys[#keys + 1] = { f + F + 1, to }
    end
  end
  return keys
end

-- Skipped during a design preview so the forced-visible tag isn't switched off.
if comp:FindTool("Team1TagMerge") and not rawget(_G, "SCOREBOARD_TAG_PREVIEW") then
  local tagFade = math.floor(TAG_FADE_SEC * fps + 0.5)
  for t = 1, 2 do
    local pre = "Team" .. t .. "Tag"
    -- 2026-09-27: tags fade in/out over TAG_FADE_SEC instead of popping.
    for _, part in ipairs({ "Merge", "BGMerge", "AccentMerge", "LineMerge" }) do
      if comp:FindTool(pre .. part) then
        local n = writeKeys(tool(pre .. part), "Blend", fadeKeys(tagOn[t], tagFade), pre .. part)
        if part == "Merge" then counts[pre] = n end
      end
    end
    if #tagTxt[t] > 0 then
      animate(tool(pre), "StyledText", tagTxt[t], pre, true)
    end
  end
end

--------------------------------------------------------------------------------
-- SCORE POP (2026-09-26)
-- When a team wins a point, its score number pops (grows SCORE_POP_SCALE and
-- eases back over SCORE_POP_SEC) and flashes its team colour (fading back to
-- white over SCORE_TINT_SEC). Only on +1 within a set — the 0-0 reset at a new
-- set and any corrections (score going down) don't animate.
--
-- Every flat stretch gets a key at BOTH ends (release, release+1 ... f-2, f-1).
-- Fusion's smooth splines take their slope from the neighbouring keys; with
-- equal values on both sides the slope is zero, so the number sits perfectly
-- still between points instead of drifting a few percent.
--------------------------------------------------------------------------------
local SCORE_POP        = true
local SCORE_POP_SCALE  = 1.18
local SCORE_POP_SEC    = 0.30
local SCORE_TINT_SEC   = 0.60
local TEAM_RGB = {
  { 0.439, 0.835, 0.286 },   -- #70D549 team 1 green  (same as build-scoreboard)
  { 0.42,  0.74,  1.00  },   -- #6BBDFF team 2 sky blue (club blue #0A84FF was too dark
                             -- on the grey score panel; matches TAG_TEXT_BLUE, 2026-09-27)
}

local function popFrames(team)
  local out, prevScore, prevSet = {}, nil, nil
  local key = "score" .. team
  for _, e in ipairs(match.events) do
    local s = tonumber(e[key]) or 0
    if prevScore ~= nil and e.set == prevSet and s == prevScore + 1 then
      out[#out + 1] = frameOf(e.t)
    end
    prevScore, prevSet = s, e.set
  end
  return out
end

-- Writes base -> peak -> base pulses at the given frames onto one numeric input.
local function pulse(node, inputName, frames, base, peak, holdFrames)
  if not node then return 0 end
  pcall(function()
    local o = node[inputName]:GetConnectedOutput()
    if o then o:GetTool():Delete() end
  end)
  pcall(function() node[inputName][0] = base end)
  local ok = pcall(function() node:AddModifier(inputName, "BezierSpline") end)
  if not ok then fail("couldn't animate " .. inputName) return 0 end

  local n, lastKey = 0, -1
  for i, f in ipairs(frames) do
    local nextF = frames[i + 1] or math.huge
    local rel = math.min(f + holdFrames, nextF - 4)
    if f - 2 > lastKey and rel > f then
      pcall(function()
        node[inputName][f - 2]   = base
        node[inputName][f - 1]   = base
        node[inputName][f]       = peak
        node[inputName][rel]     = base
        node[inputName][rel + 1] = base
      end)
      lastKey = rel + 1
      n = n + 1
    end
  end
  return n
end

-- 2026-10-14: set wins for one team -> list of { frame, resetFrame|nil }.
-- frame = the event where that team's set count goes up (the winning point, or
-- the extra "time's up" event of a forced set); resetFrame = the first event of
-- the next set (0-0), nil when no set follows (end of match).
local function setWins(team)
  local out, prev = {}, nil
  local ev = match.events
  for i, e in ipairs(ev) do
    local s = tonumber(e["sets" .. team]) or 0
    if prev ~= nil and s == prev + 1 then
      local reset = nil
      for j = i + 1, #ev do
        if (tonumber(ev[j].set) or 0) > (tonumber(e.set) or 0) then reset = frameOf(ev[j].t) break end
      end
      out[#out + 1] = { frameOf(e.t), reset }
    end
    prev = s
  end
  return out
end

-- Colour keys for one channel: white, a short flash to `col` on each point,
-- and a held `col` from each set win until its reset frame. Every flat stretch
-- has keys at both ends so the smooth spline stays flat.
local function colourKeys(popF, wins, col, tintF)
  local keys, winAt = { { 0, 1.0 } }, {}
  for _, w in ipairs(wins) do winAt[w[1]] = w[2] or -1 end
  local all = {}
  for _, f in ipairs(popF) do all[#all + 1] = f end
  for f in pairs(winAt) do
    local dup = false
    for _, g in ipairs(popF) do if g == f then dup = true end end
    if not dup then all[#all + 1] = f end
  end
  table.sort(all)
  local lastKey = 0
  for i, f in ipairs(all) do
    local nextF = all[i + 1] or math.huge
    if f - 2 > lastKey then
      keys[#keys + 1] = { f - 2, 1.0 }
      keys[#keys + 1] = { f - 1, 1.0 }
      keys[#keys + 1] = { f, col }
      local r = winAt[f]
      if r then
        if r > f + 3 then
          keys[#keys + 1] = { f + 1, col }
          keys[#keys + 1] = { r - 2, col }
          keys[#keys + 1] = { r - 1, col }
          keys[#keys + 1] = { r, 1.0 }
          keys[#keys + 1] = { r + 1, 1.0 }
          lastKey = r + 1
        else                                   -- end of match: hold to the end
          keys[#keys + 1] = { f + 1, col }
          lastKey = math.huge
        end
      else
        local rel = math.min(f + tintF, nextF - 4)
        if rel > f then
          keys[#keys + 1] = { rel, 1.0 }
          keys[#keys + 1] = { rel + 1, 1.0 }
          lastKey = rel + 1
        end
      end
    end
  end
  return keys
end

local popCheck = {}
if SCORE_POP then
  for team = 1, 2 do
    local node = comp:FindTool("Team" .. team .. "Score")
    if node then
      local frames = popFrames(team)
      local baseSize = 0.076
      pcall(function() baseSize = node.Size[0] end)
      -- a previous run's spline may still be on Size; read its first value
      if type(baseSize) ~= "number" then baseSize = 0.076 end
      local popN = pulse(node, "Size", frames, baseSize, baseSize * SCORE_POP_SCALE,
                         math.floor(SCORE_POP_SEC * fps + 0.5))
      local rgb = TEAM_RGB[team]
      local tintF = math.floor(SCORE_TINT_SEC * fps + 0.5)
      -- 2026-10-14 (Kenny): on the point that wins a set, the score turns the
      -- team colour and STAYS that colour until the next set starts (the 0-0
      -- event, hidden by the set-change dip); other points flash as before.
      local wins = setWins(team)
      for ch, input in ipairs({ "Red1", "Green1", "Blue1" }) do
        writeKeys(node, input, colourKeys(frames, wins, rgb[ch], tintF), "Team" .. team .. "Score " .. input)
      end
      counts["Team" .. team .. "SetWinColour"] = #wins
      counts["Team" .. team .. "Pop"] = popN

      -- Sanity check the curve: sample from the first pop to ~2 s later. Size
      -- must peak near base*scale and never dip noticeably below base.
      if frames[1] then
        local lo, hi = math.huge, -math.huge
        for f = frames[1] - 3, frames[1] + math.floor(2 * fps) do
          local v
          pcall(function() v = node.Size[f] end)
          if type(v) == "number" then lo = math.min(lo, v) hi = math.max(hi, v) end
        end
        popCheck[#popCheck + 1] = string.format(
          "Team%dScore pop: %d pulses, size %.4f..%.4f (base %.4f)%s", team, popN, lo, hi, baseSize,
          (lo < baseSize * 0.985) and "  *** DIPS BELOW BASE ***" or "")
      end
    end
  end
end

--------------------------------------------------------------------------------
-- POLISH (2026-09-27)
--  * sets-won pop: a team's SETS number pops + flashes its colour when they
--    win a set (same look as the score pop)
--  * set-change dip: at the first event of a new set, "SET n" and both scores
--    fade out and back in (~0.15 s each way) while they switch, instead of
--    snapping to "SET 2" / 0-0 in one frame
--  * whole-scoreboard fade in over the first 0.5 s and out over the last 0.5 s
--------------------------------------------------------------------------------
local polishNotes = {}

-- Sets-won pop
for team = 1, 2 do
  local node = comp:FindTool("Team" .. team .. "Sets")
  if node and SCORE_POP then
    local frames, prev = {}, nil
    for _, e in ipairs(match.events) do
      local s = tonumber(e["sets" .. team]) or 0
      if prev ~= nil and s == prev + 1 then frames[#frames + 1] = frameOf(e.t) end
      prev = s
    end
    local base = 0.043
    pcall(function() local v = node.Size[0] if type(v) == "number" then base = v end end)
    local n = pulse(node, "Size", frames, base, base * SCORE_POP_SCALE, math.floor(SCORE_POP_SEC * fps + 0.5))
    -- 2026-10-14 (Kenny): the number stays white; a rounded box in the team
    -- colour (Team<n>SetsChipMerge) shows behind it: on at the win, held
    -- 0.25 s, faded out by 1.4 s.
    for _, input in ipairs({ "Red1", "Green1", "Blue1" }) do
      pcall(function()
        local o = node[input]:GetConnectedOutput()
        if o then o:GetTool():Delete() end
      end)
      pcall(function() node[input] = 1.0 end)
    end
    local chip = comp:FindTool("Team" .. team .. "SetsChipMerge")
    local chipN = 0
    if chip and #frames > 0 then
      local H, F = math.floor(0.25 * fps + 0.5), math.floor(1.4 * fps + 0.5)
      local k = { { 0, 0 } }
      for _, f in ipairs(frames) do
        k[#k + 1] = { f - 2, 0 } k[#k + 1] = { f - 1, 0 } k[#k + 1] = { f, 1 }
        k[#k + 1] = { f + H, 1 } k[#k + 1] = { f + F, 0 } k[#k + 1] = { f + F + 1, 0 }
      end
      chipN = writeKeys(chip, "Blend", k, "Team" .. team .. "SetsChipMerge") > 0 and #frames or 0
    end
    polishNotes[#polishNotes + 1] = string.format("Team%dSets pop: %d, box: %d%s", team, n, chipN,
      chip and "" or " (no box node — old scoreboard build)")
  end
end

-- Set-change dip
local DIP_SEC = 0.15
do
  local D = math.max(2, math.floor(DIP_SEC * fps + 0.5))
  local dips, prevSet = {}, nil
  for _, e in ipairs(match.events) do
    local s = tonumber(e.set) or 1
    if prevSet ~= nil and s ~= prevSet then dips[#dips + 1] = frameOf(e.t) end
    prevSet = s
  end
  local keys = { { 0, 1 } }
  for _, f in ipairs(dips) do
    keys[#keys + 1] = { f - D - 1, 1 }
    keys[#keys + 1] = { f - D, 1 }
    keys[#keys + 1] = { f, 0 }
    keys[#keys + 1] = { f + D, 1 }
    keys[#keys + 1] = { f + D + 1, 1 }
  end
  local done = 0
  for _, name in ipairs({ "SetNumberMerge", "Team1ScoreMerge", "Team2ScoreMerge" }) do
    local m = comp:FindTool(name)
    if m and #dips > 0 then
      -- copy the key list: writeKeys sorts in place
      local k = {} for i, kv in ipairs(keys) do k[i] = { kv[1], kv[2] } end
      writeKeys(m, "Blend", k, name)
      done = done + 1
    end
  end
  polishNotes[#polishNotes + 1] = string.format("set-change dip: %d change(s) on %d node(s)", #dips, done)
end

-- Whole-scoreboard fade in/out
do
  local fm = comp:FindTool("FadeAllMerge")
  if fm then
    local a = comp:GetAttrs()
    local startF = a.COMPN_RenderStart or a.COMPN_GlobalStart or 0
    local endF   = a.COMPN_RenderEnd or a.COMPN_GlobalEnd
    local F = math.floor(0.5 * fps + 0.5)
    if endF and endF - startF > 4 * F then
      writeKeys(fm, "Blend", {
        { startF, 0 }, { startF + F, 1 }, { startF + F + 1, 1 },
        { endF - F - 1, 1 }, { endF - F, 1 }, { endF, 0 } }, "FadeAllMerge")
      polishNotes[#polishNotes + 1] = string.format("fade in %d-%d, fade out %d-%d", startF, startF + F, endF - F, endF)
    else
      polishNotes[#polishNotes + 1] = "fade skipped (couldn't read comp length)"
    end
  end
end

--------------------------------------------------------------------------------
-- TEAM NAMES
-- Static for the match, so no keyframes — but they DO need repositioning.
-- The builder calculated each name's centre from whatever was in its config
-- ("Opponent"). Dropping a longer name in without recalculating leaves it
-- centred on a point meant for a shorter one, which is how "Riverside Rapids"
-- ended up hanging off the end of the bar.
--------------------------------------------------------------------------------

local NAME_CHAR_W  = 0.01265  -- Barlow Condensed Bold CAPS at NAME_SIZE 0.0407 (2026-10-14: was 0.0115 at 0.037) — keep in step with build-scoreboard.lua
-- Keep in step with build-scoreboard.lua: names shown in capitals.
local NAMES_UPPERCASE = true
local NAME_MARGIN  = 0.020    -- gap from the end of the bar to the text
-- Keep BAR_WIDTH in step with build-scoreboard.lua (0.75 until 2026-09-25).
local BAR_WIDTH    = 0.875   -- 2026-10-21 (Kenny): was 0.85; keep in step with build-scoreboard.lua
local BAR_L, BAR_R = 0.5 - BAR_WIDTH / 2, 0.5 + BAR_WIDTH / 2
-- Keep these in step with build-scoreboard.lua. Names are edge-anchored now
-- (2026-09-25), so these only correct the font's side bearings: 40px from
-- each accent line on a 4K render.
local NAME1_NUDGE  = 0.0030
local NAME2_NUDGE  = -0.0015

-- Widest a name may be before it reaches the serve ball. The ball sits at
-- 0.3598 / 0.6402 (moved out from 0.3631 on 2026-09-27, Kenny) and is ~0.0093
-- wide either side of that; 0.341 still leaves ~26 px (4K) before the ball. Symmetric, so one number covers both sides.
-- The inner limit (~0.341) is fixed by the serve ball; the outer start moves
-- with the bar, so the room grows as the bar widens.
local NAME_MAX_W = 0.341 - (BAR_L + NAME_MARGIN)
local ELLIPSIS   = "..."

local CHAR_W = {
  [" "] = 0.42,
  ["i"] = 0.45, ["l"] = 0.45, ["I"] = 0.45, ["j"] = 0.45,
  ["."] = 0.45, [","] = 0.45, ["'"] = 0.45, ["!"] = 0.45, [":"] = 0.45, [";"] = 0.45,
  ["f"] = 0.60, ["t"] = 0.60, ["r"] = 0.60,
  ["W"] = 1.35, ["M"] = 1.35, ["m"] = 1.35, ["w"] = 1.35,
}

local function nameWidth(str)
  local units = 0
  for i = 1, #str do units = units + (CHAR_W[str:sub(i, i)] or 1.0) end
  return units * NAME_CHAR_W
end

-- Trim from the end and append "..." until it fits. Any trailing space is
-- stripped first, so we get "Riverside Rap..." rather than "Riverside Rap ...".
local function fitName(str, maxW)
  maxW = maxW or NAME_MAX_W
  if nameWidth(str) <= maxW then return str, false end
  -- 2026-10-02: first try dropping whole words from the end (age group /
  -- division), e.g. "THUNDERCATS POLAR 14U" next to a logo -> "THUNDERCATS".
  -- Not reported as a cut; the full name still shows on the intro/summary.
  local words = {}
  for w in str:gmatch("%S+") do words[#words + 1] = w end
  for n = #words - 1, 1, -1 do
    local t = table.concat(words, " ", 1, n)
    if nameWidth(t) <= maxW then return t, false end
  end
  local s = str
  while #s > 1 do
    s = s:sub(1, #s - 1):gsub("%s+$", "")
    if nameWidth(s .. ELLIPSIS) <= maxW then return s .. ELLIPSIS, true end
  end
  return ELLIPSIS, true
end

-- Outer-edge anchor point. The Text+ node is anchored left (Team1) or right
-- (Team2), so the gap to the end of the bar is exact for any name length —
-- no width estimate involved. (nameWidth is still used by fitName above.)
local function nameAnchor(side)
  if side == "left" then return BAR_L + NAME_MARGIN + NAME1_NUDGE end
  return BAR_R - NAME_MARGIN + NAME2_NUDGE
end

local function setName(nodeName, raw, side)
  local node = comp:FindTool(nodeName)
  if not node then fail("node not found: " .. nodeName) return end
  if not raw then return end

  if NAMES_UPPERCASE then raw = raw:upper() end

  -- 2026-09-26: if the builder placed a Team 1 logo, it already moved
  -- Team1Name inward to make room. Read that shift back off the node (so the
  -- logo size lives in one place, build-scoreboard.lua) and allow for it.
  local shift = 0
  if side == "left" and comp:FindTool("Team1Logo") then
    pcall(function()
      local c = node.Center[0]
      shift = math.max(0, (c[1] or c.X) - (BAR_L + NAME_MARGIN + NAME1_NUDGE))
    end)
  elseif side == "right" and comp:FindTool("Team2Logo") then   -- 2026-10-02
    pcall(function()
      local c = node.Center[0]
      shift = math.max(0, (BAR_R - NAME_MARGIN + NAME2_NUDGE) - (c[1] or c.X))
    end)
  end

  local shown, wasCut = fitName(raw, NAME_MAX_W - shift)
  pcall(function() node.StyledText[0] = shown end)
  pcall(function() node.HorizontalLeftCenterRight[0] = (side == "left") and -1 or 1 end)
  -- Keep the vertical position the builder gave the name (it may be in strip
  -- units since 2026-09-27); only the horizontal anchor is recalculated here.
  local cy = 0.115
  pcall(function() local c = node.Center[0]; cy = c[2] or c.Y or cy end)
  pcall(function() node.Center[0] = { nameAnchor(side) + ((side == "left") and shift or -shift), cy } end)

  if wasCut then
    fail(string.format("%q was too wide for the bar — showing %q", raw, shown))
  end
end

setName("Team1Name", match.team1, "left")
setName("Team2Name", match.team2, "right")

comp:EndUndo(true)
comp:Unlock()

--------------------------------------------------------------------------------
-- REPORT
--------------------------------------------------------------------------------

local firstF = frameOf(match.events[1].t)
local lastF  = frameOf(match.events[#match.events].t)

local rep = {}
local function say(s) rep[#rep + 1] = s print(s) end

say("=====================================================")
say(" Match applied " .. os.date("%Y-%m-%d %H:%M:%S"))
say(" From: " .. MATCH_FILE)
say(string.format(" Teams: %s vs %s", tostring(match.team1), tostring(match.team2)))
say(string.format(" Frame rate used: %g fps (from %s)", fps, fpsSource))
if AUTO_ALIGN_SETS then
  for _, n in ipairs(alignNotes) do say(" Set alignment: " .. n) end
end
say("")
for _, k in ipairs({"Team1Score", "Team2Score", "Team1Sets", "Team2Sets",
                    "SetNumber", "Team1Serve", "Team2Serve"}) do
  say(string.format("   %-12s %d keyframes", k, counts[k] or 0))
end

say("")
say(string.format(" Covers frames %d to %d (%.1f seconds at %g fps).",
    firstF, lastF, match.events[#match.events].t - match.events[1].t, fps))

-- Did it actually take? Compare the start of the match against the end.
say("")
say(" Verification — values should differ between the two frames:")
say("   Team1Score      " .. verify("Team1Score", "StyledText", firstF, lastF))
say("   Team2Score      " .. verify("Team2Score", "StyledText", firstF, lastF))
say("   Team1Sets       " .. verify("Team1Sets",  "StyledText", firstF, lastF, tonumber(match.events[#match.events].sets1 or 0) == 0))
say("   Team2Sets       " .. verify("Team2Sets",  "StyledText", firstF, lastF, tonumber(match.events[#match.events].sets2 or 0) == 0))
say("   SetNumber       " .. verify("SetNumber",  "StyledText", firstF, lastF))
say("   Team1ServeMerge " .. verify("Team1ServeMerge", "Blend", firstF, lastF))
say("   Team2ServeMerge " .. verify("Team2ServeMerge", "Blend", firstF, lastF))
for _, line in ipairs(popCheck) do say("   " .. line) end
for _, line in ipairs(polishNotes) do say("   Polish: " .. line) end
if comp:FindTool("Team1TagMerge") then
  -- (No verify() sample here: tags are on for a few seconds per set, so 9
  -- evenly spaced samples would nearly always miss them and cry "STATIC".)
  say(string.format("   Point tags: SET/MATCH POINT showing after %d event(s)", tagMoments))
else
  say("   Point tags: not built (SHOW_POINT_TAGS off in build-scoreboard.lua)")
end

if #problems > 0 then
  say("")
  say(" PROBLEMS:")
  for _, p in ipairs(problems) do say("   - " .. p) end
end
say("=====================================================")

-- Also write the report to a file, because the Fusion Console isn't always
-- reachable and a silent script is a script you can't trust.
local logPath = WORK_DIR .. "/apply-match-log.txt"
local lf = io.open(logPath, "w")
if lf then
  lf:write(table.concat(rep, "\n"))
  lf:close()
end
