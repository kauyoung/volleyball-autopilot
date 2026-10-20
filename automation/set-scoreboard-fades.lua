-- Re-times the scoreboard's whole-board fade (FadeAllMerge Blend) for the
-- intro/summary bookends (2026-09-28). Globals (seconds): SB_IN_A..SB_IN_B =
-- fade in, SB_OUT_A..SB_OUT_B = fade out. Writes _overlay_check\fade-log.txt.
-- Set-break cuts (2026-10-06, Kenny): SB_GAPS = { {hide, show_a, show_b}, ... } (seconds):
-- the board goes to 0 at `hide` (the wipe already covers the screen there), stays hidden
-- through the cut and the panel's exit, and fades back in slowly from show_a to show_b.
local msg
local ok, err = pcall(function()
  local rv = rawget(_G, "resolve") or Resolve()
  local proj = rv:GetProjectManager():GetCurrentProject()
  local sbt
  for i = 1, proj:GetTimelineCount() do
    local x = proj:GetTimelineByIndex(i)
    if x:GetName() == "Scoreboard" then sbt = x end
  end
  local comp = sbt:GetItemListInTrack("video", 1)[1]:GetFusionCompByIndex(1)
  local fm = comp:FindTool("FadeAllMerge")
  local fps = tonumber(comp:GetPrefs("Comp.FrameFormat.Rate")) or (60000 / 1001)
  local last = math.floor(sbt:GetEndFrame() - sbt:GetStartFrame() - 1)
  local function F(s) return math.max(0, math.min(last, math.floor(s * fps + 0.5))) end
  local a, b, c, d = F(SB_IN_A), F(SB_IN_B), F(SB_OUT_A), F(SB_OUT_B)
  comp:Lock()
  pcall(function() local o = fm.Blend:GetConnectedOutput() if o then o:GetTool():Delete() end end)
  fm:AddModifier("Blend", "BezierSpline")
  local keys = {}
  if a > 0 then keys[#keys + 1] = { 0, 0 } end
  keys[#keys + 1] = { a, 0 }; keys[#keys + 1] = { b, 1 }
  local gaps = rawget(_G, "SB_GAPS") or {}
  local ng = 0
  for _, gp in ipairs(gaps) do
    local h, sa, sb = F(gp[1]), F(gp[2]), F(gp[3])
    if h > b + 1 and sb < c and h < sa and sa < sb then
      keys[#keys + 1] = { h - 1, 1 }; keys[#keys + 1] = { h, 0 }
      keys[#keys + 1] = { sa, 0 }; keys[#keys + 1] = { sb, 1 }
      ng = ng + 1
    end
  end
  if c > b then keys[#keys + 1] = { c, 1 } end
  if d > c then keys[#keys + 1] = { d, 0 } end
  if last > d then keys[#keys + 1] = { last, 0 } end
  for _, kv in ipairs(keys) do fm.Blend[kv[1]] = kv[2] end
  comp:Unlock()
  msg = string.format("OK in %d-%d, out %d-%d (frames)", a, b, c, d)
  if #gaps > 0 then msg = msg .. string.format("; set breaks: %d of %d (hidden under the wipe, slow fade-in after)", ng, #gaps) end
end)
if not ok then msg = "ERROR " .. tostring(err) end
local f = io.open("C:/Users/YOURNAME/scoreboard-pipeline/_overlay_check/fade-log.txt", "w")
f:write(msg) f:close()
