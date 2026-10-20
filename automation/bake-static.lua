--[[
================================================================================
 Venom Rebels scoreboard — pre-draw the unchanging parts (speed, 2026-09-28)
================================================================================
 Run AFTER run-overlay.lua (team names and logo are final by then), with
 _G.comp set to the scoreboard comp (the runner template does this) and the
 MATCH timeline current (the image is saved next to the camera files).

 The scoreboard is one long chain of Merges, bottom to top. Most layers never
 change during a match (bar, cells, lines, accents, names, SETS labels, logo,
 SET tab, outline); a few are animated (scores, sets, serve balls, SET/MATCH
 POINT tags, SET n). This script:
   1. sorts each layer into "static" or "animated" (animated = the layer or its
      merge has any keyframed input),
   2. re-stacks all static layers, in their original order, on their own,
   3. renders that stack ONCE to "<match folder>\scoreboard-static0000.exr"
      (lossless float, with alpha) through a temporary Saver (then deleted),
   4. loads it back with a Loader ("StaticBase") and stacks the animated layers
      on top of it in their original order. The original static nodes stay in
      the comp, disconnected (not rendered) — re-run after re-applying a match.
 Pixel-identical as long as no animated layer overlaps a static layer that
 used to sit above it (verified on renders, see workflow notes).
 Writes bake-static-log.txt next to this script. _G.BAKE_STATIC_OFF = true
 skips it. Replaces hold-static.lua (TimeStretcher hold: unreliable speed and
 Resolve crashed twice when switching into a project that had it).
================================================================================
--]]
local WORK_DIR = "C:/Users/YOURNAME/scoreboard-pipeline"
local log = {}
local function say(s) log[#log + 1] = tostring(s) end

local ok, err = pcall(function()
  if rawget(_G, "BAKE_STATIC_OFF") then say("skipped (BAKE_STATIC_OFF)") return end
  local c = rawget(_G, "comp")
  local rv = rawget(_G, "resolve") or Resolve()
  local master = c:FindTool("MasterSize")
  if not master then say("ERROR: MasterSize not found") return end
  if c:FindTool("StaticBase") then say("already baked — nothing to do (rebuild the scoreboard to re-bake)") return end

  -- where to save: the match folder (next to the first camera clip)
  local tl = rv:GetProjectManager():GetCurrentProject():GetCurrentTimeline()
  local v1 = tl and tl:GetItemListInTrack("video", 1) or {}
  local clipPath = (v1[1] and v1[1]:GetMediaPoolItem()) and v1[1]:GetMediaPoolItem():GetClipProperty("File Path") or ""
  local folder = clipPath:match("^(.*)[/\\][^/\\]+$")
  if not folder or folder == "" then say("ERROR: couldn't find the match folder from the timeline's V1 clip") return end
  local stem = (folder .. "\\scoreboard-static"):gsub("\\", "/")
  local file = stem .. "0000.exr"

  local function upTool(inp)
    local o = inp and inp:GetConnectedOutput()
    return o and o:GetTool() or nil
  end
  local function regid(t) return t and t:GetAttrs().TOOLS_RegID or "" end
  local function inputs(tool)
    local l = {}
    for _, v in pairs(tool:GetInputList() or {}) do
      if type(v) ~= "string" and type(v) ~= "number" and type(v) ~= "boolean" then l[#l + 1] = v end
    end
    return l
  end
  local function driven(tool)
    for _, inp in ipairs(inputs(tool)) do
      local up = nil
      pcall(function() local o = inp:GetConnectedOutput() if o then up = o:GetTool() end end)
      if up then
        local id = regid(up)
        if id:match("Spline") or id:match("Path") or id == "Expression" then return true end
      end
    end
    return false
  end
  local function animatedTree(tool, seen)
    seen = seen or {}
    if not tool or seen[tool] then return false end
    seen[tool] = true
    if driven(tool) then return true end
    for _, v in ipairs(inputs(tool)) do
      local up = nil
      pcall(function() local o = v:GetConnectedOutput() if o then up = o:GetTool() end end)
      if up then
        local id = regid(up)
        if not (id:match("Spline") or id:match("Path")) and id ~= "Merge" then
          if animatedTree(up, seen) then return true end
        end
      end
    end
    return false
  end

  -- 1. the chain, bottom -> top
  local chain = {}
  local t = upTool(master.Input)
  while t and regid(t) == "Merge" do
    table.insert(chain, 1, t)
    t = upTool(t.Background)
  end
  local base = t
  if not base or animatedTree(base) then say("ERROR: bottom layer missing or animated — nothing changed") return end

  -- Layers built from a MOVING image stay live. Still pictures (the team logos,
  -- .png) are baked since 2026-10-03: kept live they cost ~9 s per 30 s of
  -- export (35.4 s -> 26.3 s with them baked; the whole rest of the scoreboard
  -- costs ~2 s). (2026-09-28 they were kept live because the one-off render
  -- resampled their edges slightly differently — re-checked 2026-10-03.)
  -- _G.BAKE_KEEP_LOGOS_LIVE = true restores the old behaviour.
  local KEEP_STILLS_LIVE = rawget(_G, "BAKE_KEEP_LOGOS_LIVE")
  local function hasLoader(tool, seen)
    seen = seen or {}
    if not tool or seen[tool] then return false end
    seen[tool] = true
    if regid(tool) == "Loader" then
      local clip = ""
      pcall(function() clip = tostring(tool:GetAttrs().TOOLST_Clip_Name[1] or "") end)
      if not KEEP_STILLS_LIVE and clip:lower():match("%.png$") then return false end
      return true
    end
    for _, v in ipairs(inputs(tool)) do
      local up = nil
      pcall(function() local o = v:GetConnectedOutput() if o then up = o:GetTool() end end)
      if up and regid(up) ~= "Merge" and hasLoader(up, seen) then return true end
    end
    return false
  end
  local statics, dyns = {}, {}
  for _, m in ipairs(chain) do
    local fg = upTool(m.Foreground)
    if driven(m) or animatedTree(fg) or hasLoader(fg) then dyns[#dyns + 1] = m else statics[#statics + 1] = m end
  end
  local sn, dn = {}, {}
  for _, m in ipairs(statics) do sn[#sn + 1] = m:GetAttrs().TOOLS_Name end
  for _, m in ipairs(dyns) do dn[#dn + 1] = m:GetAttrs().TOOLS_Name end
  say(string.format("chain: %d merges above %s", #chain, base:GetAttrs().TOOLS_Name))
  say("static (" .. #statics .. "): " .. table.concat(sn, ", "))
  say("animated (" .. #dyns .. "): " .. table.concat(dn, ", "))
  if #dyns == 0 then say("ERROR: no animated layers found — run apply-match first") return end

  -- 2. re-stack the static layers on their own
  c:Lock()
  c:StartUndo("Bake static layers")
  local prev = base
  for _, m in ipairs(statics) do m.Background = prev.Output prev = m end
  local staticTop = prev
  c:EndUndo(true)
  c:Unlock()

  -- 3. render it once
  os.remove(file)
  local sv = c:AddTool("Saver", -32768, -32768)
  sv:SetAttrs({ TOOLS_Name = "StaticSaver" })
  sv.Input = staticTop.Output
  sv.Clip = stem .. ".exr"
  pcall(function() sv.OutputFormat = "OpenEXRFormat" end)
  -- HiQ = true: without it Fusion renders draft quality (less edge smoothing on
  -- text/masks) — measured up to 26/255 off on ~5,000 edge pixels.
  -- Batch (quiet) mode, so Resolve doesn't pop up a "Render completed!" box
  -- that blocks all scripting until someone clicks it.
  local F = rawget(_G, "fu") or rawget(_G, "fusion") or (rv.Fusion and rv:Fusion())
  pcall(function() F:SetBatch(true) end)
  local r = c:Render({ Start = 0, End = 0, Tool = sv, Wait = true, HiQ = true })
  pcall(function() F:SetBatch(false) end)
  sv:Delete()
  local fh = io.open(file, "rb")
  if not (r and fh) then
    say("ERROR: couldn't write " .. file .. " — scoreboard left as it was (static layers restacked, still live)")
    -- put the static stack back under the animated layers so nothing is lost
    local p2 = staticTop
    for _, m in ipairs(dyns) do m.Background = p2.Output p2 = m end
    master.Input = p2.Output
    return
  end
  fh:close()

  -- 4. load it and put the animated layers on top
  c:Lock()
  c:StartUndo("Use baked static layers")
  local ld = c:AddTool("Loader", -32768, -32767)
  ld:SetAttrs({ TOOLS_Name = "StaticBase" })
  ld.Clip = file
  prev = ld
  for _, m in ipairs(dyns) do m.Background = prev.Output prev = m end
  master.Input = prev.Output
  c:EndUndo(true)
  c:Unlock()
  say("saved " .. file)
  say("BAKED OK")
end)
if not ok then say("LUA ERROR: " .. tostring(err)) end
local f = io.open(WORK_DIR .. "/bake-static-log.txt", "w")
if f then f:write(table.concat(log, "\n")) f:close() end
