--[[
================================================================================
 Venom Rebels scoreboard — place the scoreboard clip (no mouse needed)
================================================================================

 Replaces the old on-screen step (drag "Abstract Mesh" onto V2, Ctrl+D to set
 its length, drag it to the start). Added 2026-09-27.

 How it works — two Resolve API facts make this possible:
   1. InsertFusionGeneratorIntoTimeline() respects the timeline's In/Out marks,
      so the generator comes out exactly N frames long. But it always lands on
      V1 (the insert destination) and would shove the footage aside.
   2. So it's inserted into its OWN empty timeline called "Scoreboard", and that
      timeline is then dropped onto V2 of the match timeline with
      AppendToTimeline (which does accept a track number and a start position).
 The scoreboard's Fusion comp lives inside the "Scoreboard" timeline's V1 clip
 — run-overlay.lua is pointed at that comp (see _overlay_check/_runner_template.lua).
 Verified on the Thundercats footage: identical frames to the dragged version,
 same export speed.

 Run with the MATCH timeline current (right after assemble-match.lua):
   dofile("C:/Users/YOURNAME/scoreboard-pipeline/place-scoreboard.lua")
 Writes place-log.txt next to this script.
================================================================================
--]]

local WORK_DIR  = "C:/Users/YOURNAME/scoreboard-pipeline"
local GENERATOR = "Abstract Mesh"   -- any Fusion generator works; build-scoreboard replaces its contents
local SB_NAME   = "Scoreboard"

local log = {}
local function say(s) log[#log + 1] = tostring(s) print(tostring(s)) end
local function finish()
  local f = io.open(WORK_DIR .. "/place-log.txt", "w")
  if f then f:write(table.concat(log, "\n")) f:close() end
end

local ok, err = pcall(function()
  local resolve = rawget(_G, "resolve") or Resolve()
  local project = resolve:GetProjectManager():GetCurrentProject()
  local mp      = project:GetMediaPool()
  local match   = project:GetCurrentTimeline()
  if not match then say("ERROR: no current timeline — run assemble-match.lua first.") return end
  if match:GetName() == SB_NAME then say("ERROR: the current timeline is the Scoreboard one — switch to the match timeline.") return end

  local st = match:GetStartFrame()
  local N  = match:GetEndFrame() - st
  say("Match timeline: " .. match:GetName() .. " (" .. N .. " frames)")

  -- Refuse to double up.
  if match:GetTrackCount("video") >= 2 and #match:GetItemListInTrack("video", 2) > 0 then
    say("ERROR: V2 already has something on it — nothing changed.")
    return
  end
  for i = 1, project:GetTimelineCount() do
    if project:GetTimelineByIndex(i):GetName() == SB_NAME then
      say("ERROR: a timeline called '" .. SB_NAME .. "' already exists in this project — nothing changed.")
      return
    end
  end

  -- 1. Generator in its own timeline, exactly N frames long.
  local sb = mp:CreateEmptyTimeline(SB_NAME)
  if not sb then say("ERROR: couldn't create the Scoreboard timeline.") return end
  project:SetCurrentTimeline(sb)
  sb:SetMarkInOut(0, N - 1)
  sb:SetCurrentTimecode(sb:GetStartTimecode())
  local gen = sb:InsertFusionGeneratorIntoTimeline(GENERATOR)
  sb:ClearMarkInOut()
  local sbItems = sb:GetItemListInTrack("video", 1)
  local gDur = (#sbItems == 1) and sbItems[1]:GetDuration() or -1
  say(string.format("Scoreboard timeline: generator %s, %d frames", gen and "inserted" or "NOT inserted", gDur))

  -- 2. Find that timeline in the Media Pool.
  local mpi
  local function scan(folder)
    for _, c in ipairs(folder:GetClipList()) do
      if c:GetName() == SB_NAME and c:GetClipProperty("Type") == "Timeline" then mpi = c end
    end
    for _, sub in ipairs(folder:GetSubFolderList()) do scan(sub) end
  end
  scan(mp:GetRootFolder())

  -- 3. Drop it onto V2 of the match timeline at frame 0.
  project:SetCurrentTimeline(match)
  if not mpi then say("ERROR: couldn't find the Scoreboard timeline in the Media Pool.") return end
  if match:GetTrackCount("video") < 2 then match:AddTrack("video") end
  mp:AppendToTimeline({ { mediaPoolItem = mpi, startFrame = 0, endFrame = N,
                          trackIndex = 2, recordFrame = st, mediaType = 1 } })

  -- 4. Verify.
  local v2 = match:GetItemListInTrack("video", 2)
  local good = (#v2 == 1) and (v2[1]:GetStart() == st) and (v2[1]:GetDuration() == N)
               and (gDur == N) and (match:GetEndFrame() - st == N)
  if #v2 == 1 then
    say(string.format("V2: %s, start offset %d, %d frames", v2[1]:GetName(), v2[1]:GetStart() - st, v2[1]:GetDuration()))
  end
  say(good and "PLACED OK" or "*** PLACEMENT PROBLEM — check V2 by hand ***")
end)
if not ok then say("LUA ERROR: " .. tostring(err)) end
finish()
