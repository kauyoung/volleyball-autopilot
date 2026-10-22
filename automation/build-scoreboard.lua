--[[
================================================================================
 Venom Rebels scoreboard — Fusion node graph builder
================================================================================

 Builds the entire scoreboard node graph described in
 fusion-scoreboard-walkthrough.md, correctly merged and correctly named.

 HOW TO RUN
   1. Edit page -> add a Fusion Composition to V2 -> click the Fusion tab.
   2. Workspace -> Console. Open this FIRST — it is the only place this
      script's output and warnings appear. If the Console window doesn't show
      up, it has probably remembered a position on a monitor you're no longer
      using; drag it back or reset the UI layout.
   3. Workspace -> Scripts -> Comp -> build-scoreboard
      This file must live in:
        %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Comp\
      Editing the copy in your working folder does NOT change what the Scripts
      menu runs — copy it over each time, or run it straight from source with:
        dofile("C:/Users/YOURNAME/scoreboard-pipeline/build-scoreboard.lua")

 BEFORE EACH MATCH
   Change TEAM2_NAME below and re-run. Do NOT type the opponent's name into
   the Team2Name node in Fusion:
     - this script computes each name's X position FROM the string, so a name
       typed into the node keeps the position calculated for the old one; and
     - CLEAR_EXISTING wipes the graph on every run, so it would be lost anyway.

 WARNING — CLEAR_EXISTING is true, so every run deletes the whole graph and
   rebuilds it. That's harmless today. It stops being harmless the moment the
   phase-2 script writes score/serve keyframes: re-running this builder will
   destroy them. Set CLEAR_EXISTING = false before keyframing a real match.

 Node names match the walkthrough exactly, so the phase-2 keyframing script
 will find them. Nothing needs finishing by hand.
================================================================================
--]]

--------------------------------------------------------------------------------
-- CONFIG
--------------------------------------------------------------------------------

-- 2026-09-27: bolder version (strokes ~35% thicker) so the ball matches the
-- weight of the bold text around it. The original thin icon is still there as
-- volleyball-serve-icon.png if we ever want it back.
-- 2026-10-20 (Kenny): now a photo of the OVA 14U ball (Mikasa VQ200W) with a
-- thin white rim, 512px. The drawn icon above is the fallback: point this back
-- at volleyball-serve-icon-bold.png and set SERVE_SIZE to 0.14.
-- Repo copy: the drawn icon (assets/volleyball-serve-icon-bold.png). The author's own build
-- uses a photo of the league ball at SERVE_SIZE 0.168 (photo not included).
local SERVE_ICON_PATH = [[C:\Users\YOURNAME\Documents\Resolve Assets\volleyball-serve-icon-bold.png]]

-- auto-overlay.lua fills these in from the match JSON automatically (via the
-- SCOREBOARD_TEAM1/2 globals). The values below are only used when this
-- script is run on its own.
local TEAM1_NAME = rawget(_G, "SCOREBOARD_TEAM1") or "Venom Rebels"
local TEAM2_NAME = rawget(_G, "SCOREBOARD_TEAM2") or "Opponent"

-- Team names are shown in capitals (broadcast style), whatever was typed in
-- the scorekeeper. Keep in step with NAMES_UPPERCASE in apply-match.lua.
local NAMES_UPPERCASE = true
if NAMES_UPPERCASE then TEAM1_NAME, TEAM2_NAME = TEAM1_NAME:upper(), TEAM2_NAME:upper() end

-- 2026-09-26: switched from Gotham to Barlow Condensed (free, Google Fonts,
-- OFL licence — fine for YouTube). Sizes below were raised to suit it.
local FONT       = "Barlow Condensed"
local FONT_STYLE = "SemiBold"

-- Team names only: Gotham Narrow fits ~20% more characters in the same space
-- and stays in the same family as everything else on the bar. (Narrow is
-- installed in Bold only.) Keep in step with NAME_CHAR_W in apply-match.lua.
local NAME_FONT       = "Barlow Condensed"
local NAME_FONT_STYLE = "Bold"

-- Width of the whole bar, as a fraction of frame width BEFORE OVERALL_SIZE.
-- Was 0.75; 0.85 gives each team-name cell 0.05 more (~135px at 4K after the
-- 0.70 scale). The score/sets cells in the middle don't move — only the two
-- outer name cells grow. Keep in step with BAR_WIDTH in apply-match.lua.
-- 2026-10-21 (Kenny): 0.85 -> 0.875 (+3%, ~36px further out each end at 4K) so
-- "ANCASTER LIONS STEALTH" fits in full. Inner layout (scores, SETS, serve balls) unchanged.
local BAR_WIDTH = 0.875

local CLEAR_EXISTING = true    -- true = delete every node except MediaOut1 first

-- 2026-09-26 position check: YouTube's player controls (progress bar + buttons)
-- cover roughly the bottom 8% of the picture whenever the video is paused or
-- the mouse moves. The bar used to start ~7.5% up, so its bottom edge and the
-- whole SET pill vanished under them. BAR_RAISE lifts the finished bar by this
-- fraction of frame height (applied on the MasterSize Transform, AFTER scaling)
-- so its bottom edge sits at ~10%; the SET pill moved from below the bar to
-- above it (PILL_ABOVE) so nothing is left in the controls zone.
local BAR_RAISE  = 0.025
local PILL_ABOVE = true

-- Look of the "SET n" box (and the SET POINT tags, which share its row):
--   "float"  separate rounded pill floating above the bar, wide letter-spacing
--            (the original — Kenny, 2026-09-27: "looks out of place")
--   "clean"  same floating pill, but tighter, bolder, brighter text, snug pill
--   "tab"    a tab joined to the top of the bar, exactly as wide as the grey
--            score cell and the same grey, so it reads as the score box's
--            header; SET POINT tags become matching tabs on the name cells
-- _G.SCOREBOARD_PILL_STYLE overrides this for design previews.
local PILL_STYLE = rawget(_G, "SCOREBOARD_PILL_STYLE") or "tab"   -- chosen 2026-09-27
local BAR_TOP    = 0.115 + 0.0575            -- top edge of the bar (pre-MasterSize)
local TAB_H      = 0.052
-- The SET tab must be EXACTLY the score cell's shade, or the outline/separator
-- lines (white 0.16 on top) read brighter on one than the other (Kenny,
-- 2026-09-27). The cell is white 0.12 over black 0.74, i.e. effective alpha
-- 1 - 0.26*0.88 = 0.771 and colour 0.1252/0.771 = 0.162 — same result over
-- any background video.
local TAB_GREY   = { 0.162, 0.162, 0.162 }
local TAB_ALPHA  = 0.771
-- Faint outline around the whole shape (bar + SET tab, and each SET POINT tab
-- while it shows) — Kenny, 2026-09-27. Only used with the "tab" style.
local OUTLINE       = true
-- Matched to the cell separators (0.0008 wide at alpha 0.16) so the tab's side
-- lines continue the score cell's separator lines exactly (Kenny, 2026-09-27:
-- at 3 px / 0.22 they sat a few pixels off and looked like two lines).
local OUTLINE_ALPHA = 0.16
local OUTLINE_PX    = 0.0008 * 3840 * 0.70   -- = separator width on the 4K frame (~2.15 px)
local TAB_EXT       = 0.02     -- tabs are drawn this far down INTO the bar, then the
                               -- bar's shape is cut out, so they join with no seam

-- Team logo (optional). If a PNG named after Team 1 exists in LOGO_DIR
-- (lower-case, spaces -> dashes, e.g. "venom-rebels.png"), it's placed at the
-- outer end of the Team 1 cell and the name shifts inward to make room. No file
-- = no logo, name back at the edge (so Thunderbolts works without one).
-- apply-match.lua detects the Team1Logo node and allows for it when fitting.
local LOGO_DIR    = "C:/Users/YOURNAME/scoreboard-pipeline/team-logos/"
local LOGO_H      = 0.78    -- logo height as a fraction of the bar's height
local LOGO_START  = 0.018   -- bar end -> logo left edge (pre-MasterSize units)
local LOGO_GAP    = 0.010   -- logo right edge -> team name

-- Depth: a faint top sheen on the bar + a softer, stronger drop shadow.
local SHEEN_ALPHA   = 0.07
local SHADOW_SOFT   = 10
local SHADOW_ALPHA  = 0.60
-- 2026-09-27 speed work — measured, not guessed:
--   * The Shadow node re-blurred the whole overlay every frame and was ~60% of
--     the YouTube export time (30 s of video: 89 s with it, 38 s without).
--   * Rendered with and without it, the frames differ by at most 10/255 on a
--     single pixel — i.e. at these settings it was effectively invisible.
-- So the default is now "none" (identical look, much faster).
--   "tool":  the old Fusion Shadow node on the whole overlay
--   "plate": a soft shape under the bar + SET tab (visible; NOT the approved look)
--   "none":  no shadow node (default — matches the approved renders)
local SHADOW_MODE      = rawget(_G, "SCOREBOARD_SHADOW_MODE") or "none"
local SHADOW_EDGE      = rawget(_G, "SCOREBOARD_SHADOW_EDGE") or 0.006  -- mask SoftEdge (calibrated)
local SHADOW_LEVEL     = rawget(_G, "SCOREBOARD_SHADOW_LEVEL") or (0.60 * 0.74)

-- SET POINT / MATCH POINT tags (approved 2026-09-26: style "text" = dark pill,
-- words in the team colour). apply-match.lua switches them on and off.
local SHOW_POINT_TAGS = true
local TAG_STYLE       = "text"
local TAG_TEXT_BLUE   = { 0.42, 0.74, 1.00 }   -- #6BBDFF — same as BLUE (one blue everywhere)
-- Design previews only: _G.SCOREBOARD_TAG_PREVIEW = { side=1|2, text=..., style=... }
local TAG_PREVIEW = rawget(_G, "SCOREBOARD_TAG_PREVIEW")

-- Overall scale of the whole scorebar. 1.0 = the original full-width version.
-- This drives the MasterSize Transform, which scales about the bar's own centre
-- so the bar stays put at the bottom of frame as you change it.
local OVERALL_SIZE = 0.75   -- 2026-10-14 (Kenny): 0.70 -> 0.75, easier to read on a phone

-- Serve ball size, relative to the SOURCE PNG (512px), not the frame.
-- Set by measuring the render, not by calculation: the icon has transparent
-- padding inside its 512px canvas, so the visible ball is meaningfully smaller
-- than the canvas and the arithmetic (512 x size) overstates it. At 0.11 the
-- ball measured ~80% of the team name's cap height; 0.14 brings it level.
-- 2026-10-20 (Kenny): 0.168 = the photo ball 20% bigger than the drawn icon
-- (~64px across on the finished 4K frame; still clears names and the divider).
local SERVE_SIZE = 0.14    -- repo: drawn icon (0.168 = the author's photo ball)

-- Club colours (from the brief — locked, don't change)
local GREEN = { 0.439, 0.835, 0.286 }   -- #70D549  Venom
-- 2026-09-27: one blue everywhere (Kenny). Was the club blue #0A84FF, which
-- was too dark to read as text; sky blue #6BBDFF is now used for the accent
-- line, tag words and score flash alike.
local BLUE  = { 0.42,  0.74,  1.00  }   -- #6BBDFF  opponent
local BLACK = { 0.008, 0.012, 0.012 }   -- #020303  club black
local WHITE = { 1.0,   1.0,   1.0   }

--------------------------------------------------------------------------------
-- SETUP
--------------------------------------------------------------------------------

local comp = comp or (fusion and fusion:GetCurrentComp())
if not comp then
  print("ERROR: No composition found. Open the Fusion page on a Fusion Composition clip, then run again.")
  return
end

-- Node graph layout grid
local COL, ROW = 1, 1
local function pos(col, row) return col * 1.1, row * 1.1 end

-- Tidy layout. Every node gets placed again as the chain is built, so that each
-- Merge sits in one straight row with the element it composites directly below
-- it, and that element's mask (or loader) directly below again:
--
--   BarBG ─ Merge1 ─ Merge2 ─ Merge3 ─ ...      <- row 0
--             │        │        │
--         ScoreCell ScoreDiv  SepLeft           <- row 1  (the new element)
--             │        │        │
--          ...Shape  ...Shape ...Shape          <- row 2  (its mask)
--
-- Without this, elements keep whatever column they happened to be created in,
-- so the connecting wires fan out across the graph and cross each other.
local flow = comp.CurrentFrame and comp.CurrentFrame.FlowView
local childOf = {}

local function setPos(tool, col, row)
  if tool and flow then
    pcall(function() flow:SetPos(tool, col * 1.1, row * 1.1) end)
  end
end

--------------------------------------------------------------------------------
-- HELPERS  (defensive: input names differ slightly between Resolve versions,
--           so every set is wrapped — a miss warns instead of aborting)
--------------------------------------------------------------------------------

local warnings = {}

local function warn(msg)
  warnings[#warnings + 1] = msg
end

local function setv(tool, name, value)
  if not tool then return end
  local ok = pcall(function() tool[name][0] = value end)
  if not ok then
    ok = pcall(function() tool:SetInput(name, value, 0) end)
  end
  if not ok then
    warn(string.format("Could not set '%s' on %s — set it by hand in the Inspector.",
                       name, tool:GetAttrs().TOOLS_Name or "?"))
  end
end

local function setPoint(tool, name, x, y)
  if not tool then return end
  local ok = pcall(function() tool[name][0] = { x, y } end)
  if not ok then
    ok = pcall(function() tool:SetInput(name, { x, y }, 0) end)
  end
  if not ok then
    warn(string.format("Could not set point '%s' on %s — position it by hand.",
                       name, tool:GetAttrs().TOOLS_Name or "?"))
  end
end

--------------------------------------------------------------------------------
-- STRIP CANVAS (2026-09-27, speed)
-- Every layer used to be a full 3840x2160 image, even though the scoreboard
-- only covers a band near the bottom — ~40 full 4K layers composited per frame
-- made the YouTube export ~4x slower than the footage alone. Now every layer is
-- a 3840 x STRIP_HPX strip covering frame heights STRIP_Y0 .. STRIP_Y0 +
-- STRIP_HPX/2160, and one final merge drops the finished strip into the 4K
-- frame. All the design numbers below are still written in FULL-FRAME units;
-- SYp()/SH() convert vertical positions/heights to strip units, so the look is
-- unchanged. STRIP = false builds the old full-frame way.
--------------------------------------------------------------------------------
local STRIP     = true
local STRIP_Y0  = 0.012   -- bottom of the strip, fraction of frame height
local STRIP_HPX = 512     -- strip height in pixels (covers 0.012 .. 0.249)
local FW, FH = 3840, 2160
pcall(function()
  FW = comp:GetPrefs("Comp.FrameFormat.Width")  or FW
  FH = comp:GetPrefs("Comp.FrameFormat.Height") or FH
end)
local SY = STRIP and (FH / STRIP_HPX) or 1
local Y0 = STRIP and STRIP_Y0 or 0
local function SYp(y) return (y - Y0) * SY end   -- frame y -> canvas y
local function SH(h)  return h * SY end          -- frame height -> canvas height
-- centre of the strip in full-frame units (where the final merge puts it)
local STRIP_CENTRE_Y = STRIP and (STRIP_Y0 + (STRIP_HPX / FH) / 2) or 0.5

local function canvas(tool, isMask)
  if not tool then return end
  if STRIP then
    setv(tool, "UseFrameFormatSettings", 0)
    if isMask then
      setv(tool, "MaskWidth", FW) setv(tool, "MaskHeight", STRIP_HPX)
    else
      setv(tool, "Width", FW) setv(tool, "Height", STRIP_HPX)
    end
  else
    setv(tool, "UseFrameFormatSettings", 1)
  end
end

local function add(toolID, name, col, row)
  local x, y = pos(col, row)
  local t = comp:AddTool(toolID, x, y)
  if not t then
    warn(string.format("Could not create a '%s' node (for %s). Add it by hand.", toolID, name))
    return nil
  end
  t:SetAttrs({ TOOLS_Name = name })
  return t
end

-- A "plate": solid-colour Background masked by a RectangleMask.
-- This is the Background + Rectangle-in-the-blue-input pattern from the guide.
local function plate(name, colour, alpha, rect, col, row)
  local bg = add("Background", name, col, row)
  if not bg then return nil end
  setv(bg, "TopLeftRed",   colour[1])
  setv(bg, "TopLeftGreen", colour[2])
  setv(bg, "TopLeftBlue",  colour[3])
  -- NOTE: don't put the translucency on the Background's own alpha. Once an
  -- Effect Mask is attached, the mask drives the alpha channel and the
  -- Background's alpha is ignored — which is why a 0.74 bar renders solid.
  -- The mask's Level is the lever that actually works (set below).
  setv(bg, "TopLeftAlpha", 1.0)
  canvas(bg)

  local mask = add("RectangleMask", name .. "Shape", col, row - 1)
  if mask then
    canvas(mask, true)
    setv(mask, "Level", alpha)   -- this is the element's real opacity
    setv(mask, "Width",  rect.w)
    setv(mask, "Height", SH(rect.h))
    setPoint(mask, "Center", rect.x, SYp(rect.y))
    setv(mask, "CornerRadius", rect.r or 0)

    -- Connect the mask into the Background's Effect Mask (the blue input).
    -- Note: a RectangleMask's output is named "Mask", NOT "Output" — assigning
    -- mask.Output here silently does nothing and the Background fills frame.
    pcall(function() bg:ConnectInput("EffectMask", mask) end)

    local connected = false
    pcall(function() connected = bg.EffectMask:GetConnectedOutput() ~= nil end)
    if not connected then
      pcall(function() bg.EffectMask = mask.Mask end)
      pcall(function() connected = bg.EffectMask:GetConnectedOutput() ~= nil end)
    end
    if not connected then
      warn(string.format("%s: mask not connected — drag %s into its blue input by hand.",
                         name, name .. "Shape"))
    end
    childOf[bg] = mask   -- so the layout pass can stack it under its Background
  end
  return bg
end

local function text(name, str, size, colour, alpha, x, y, col, row)
  local t = add("TextPlus", name, col, row)
  if not t then return nil end
  canvas(t)
  setv(t, "StyledText", str)
  setv(t, "Font",  FONT)
  setv(t, "Style", FONT_STYLE)
  setv(t, "Size",  size)
  setv(t, "Red1",   colour[1])
  setv(t, "Green1", colour[2])
  setv(t, "Blue1",  colour[3])
  setv(t, "Alpha1", alpha or 1.0)
  setPoint(t, "Center", x, SYp(y))
  return t
end

--------------------------------------------------------------------------------
-- BUILD
--------------------------------------------------------------------------------

comp:Lock()
comp:StartUndo("Build Venom scoreboard")

-- Optionally clear the graph
if CLEAR_EXISTING then
  for _, t in pairs(comp:GetToolList(false)) do
    local n = t:GetAttrs().TOOLS_Name or ""
    if not n:match("^MediaOut") then t:Delete() end
  end
end

local mediaOut = comp:FindTool("MediaOut1")

-- Step 2 — the bar --------------------------------------------------------
local top = plate("BarBG", BLACK, 0.74,
                  { w = BAR_WIDTH, h = 0.115, x = 0.5, y = 0.115, r = 0.50 }, COL, ROW)

if not top then
  comp:EndUndo(true) comp:Unlock()
  print("ERROR: could not create the base bar. Aborting.")
  return
end

setPos(top, 0, 0)             -- BarBG starts the row
setPos(childOf[top], 0, 1)    -- BarShape sits under it

local mergeCount = 0

-- Stack a new element on top of everything so far.
-- previous -> orange (Background) | new -> green (Foreground)
local function stack(element, name, blend)
  if not element then return end
  mergeCount = mergeCount + 1
  local m = add("Merge", name or ("Merge" .. mergeCount), COL + mergeCount, ROW)
  if not m then return end
  m.Background = top.Output      -- orange: everything so far
  m.Foreground = element.Output  -- green:  the one new thing
  if blend then setv(m, "Blend", blend) end

  -- Line this merge up with the element it composites, and the element's mask
  -- or loader below that. Keeps every wire short and vertical.
  setPos(m, mergeCount, 0)
  setPos(element, mergeCount, 1)
  setPos(childOf[element], mergeCount, 2)

  top = m
end

local function place(element, name, blend)
  stack(element, name, blend)
end

-- Depth: a faint white sheen across the upper part of the bar, soft-edged and
-- inset from the rounded ends so it never pokes past the bar's outline. Reads
-- as light falling on the top of the bar rather than a flat black strip.
local sheen = plate("BarSheen", WHITE, SHEEN_ALPHA,
      { w = BAR_WIDTH - 0.05, h = 0.048, x = 0.5, y = 0.115 + 0.030, r = 0.5 }, COL + 1, ROW + 2)
if sheen and childOf[sheen] then setv(childOf[sheen], "SoftEdge", 0.012) end
place(sheen)

-- Step 3 — score cell, hairline, separators -------------------------------
-- White at 0.12 over the black bar reads as a lighter grey panel, so the live
-- score stands out from the name/sets cells. (Was 0.055 — barely visible.)
place(plate("ScoreCellBG", WHITE, 0.12,
      { w = 0.134, h = 0.115, x = 0.5, y = 0.115, r = 0 }, COL + 1, ROW + 2))

-- Divider between the two live scores. Raised from 0.22 to 0.50 and thickened
-- from 0.0006 to 0.001. Both were needed: at OVERALL_SIZE 0.7 the original
-- hairline lands on ~1.6 screen pixels at 4K, which renders soft and washed out.
place(plate("ScoreDivider", WHITE, 0.50,
      { w = 0.0010, h = 0.072, x = 0.5, y = 0.115 }, COL + 2, ROW + 2))

-- Cell separators. All four share one weight so the bar reads as five cells:
--   [ name ] | [ sets ] | [ score ] | [ sets ] | [ name ]
-- Raised from 0.10 to 0.16 for the same scale-down reason as above.
place(plate("SepLeft", WHITE, 0.16,
      { w = 0.0008, h = 0.115, x = 0.433, y = 0.115 }, COL + 3, ROW + 2))

place(plate("SepRight", WHITE, 0.16,
      { w = 0.0008, h = 0.115, x = 0.567, y = 0.115 }, COL + 4, ROW + 2))

-- Dividers between each team name and its SETS column, at 0.379 / 0.621.
-- These sit 0.027 from the SETS columns (0.406 / 0.594) — exactly the same gap
-- the SETS columns have to the score separators at 0.433 / 0.567 — so each
-- SETS block is optically centred in its own cell.
place(plate("SepNameLeft", WHITE, 0.16,
      { w = 0.0008, h = 0.115, x = 0.379, y = 0.115 }, COL + 4, ROW + 4))

place(plate("SepNameRight", WHITE, 0.16,
      { w = 0.0008, h = 0.115, x = 0.621, y = 0.115 }, COL + 4, ROW + 6))

-- Step 4 — team accent bars -----------------------------------------------
-- 2026-09-27: thicker and taller (was 0.0016 x 0.052) — the thin short lines
-- looked detached from the bar. 0.070 tall still clears the rounded ends.
local ACCENT_W, ACCENT_H = 0.0026, 0.070
place(plate("AccentLeft", GREEN, 1.0,
      { w = ACCENT_W, h = ACCENT_H, x = 0.5 - BAR_WIDTH / 2 + 0.0085, y = 0.115, r = 1.0 }, COL + 5, ROW + 2))

place(plate("AccentRight", BLUE, 1.0,
      { w = ACCENT_W, h = ACCENT_H, x = 0.5 + BAR_WIDTH / 2 - 0.0085, y = 0.115, r = 1.0 }, COL + 6, ROW + 2))

-- Step 5 — text ------------------------------------------------------------
-- TEAM NAMES ---------------------------------------------------------------
-- Text+ ignores a left/right anchor when it's set from a script, so both names
-- are centre-anchored. A fixed centre gives UNEQUAL margins the moment the two
-- names differ in length — "Venom Rebels" sat nearer its edge than "Opponent"
-- did. So instead of hard-coding the centre, we work back from the outer edge:
-- estimate the name's width, then place its centre so the OUTER edge always
-- lands NAME_MARGIN in from the end of the bar. Both sides then match, whatever
-- the opponent is called.
local NAME_SIZE   = 0.0407  -- Barlow Condensed; 2026-10-14 (Kenny): +10% on top of the bigger board (was 0.037; 0.026 with Gotham Narrow)
local NAME_CHAR_W = 0.01265  -- Barlow Condensed Bold CAPS at 0.0407 (= 0.0115 measured at 0.037, x1.1; kept slightly conservative)
local NAME_MARGIN = 0.020    -- gap from the end of the bar to the start of the text
local BAR_L, BAR_R = 0.5 - BAR_WIDTH / 2, 0.5 + BAR_WIDTH / 2

-- Manual trim, if a particular pair of names still looks lopsided to the eye.
-- Positive numbers move the name to the RIGHT. Units are fractions of frame
-- width, so 0.002 is about 8px on a 4K frame.
-- -0.003 shifts Team2Name 8px left on the finished 4K frame. Note the division:
-- these units are applied BEFORE the MasterSize Transform, so they get scaled by
-- OVERALL_SIZE. 8 / (3840 * 0.70) = 0.003, not 8 / 3840.
-- 2026-09-25: names are now edge-anchored (see nameAnchor below), so these only
-- correct Gotham's side bearings. Measured on a 4K render: left gap 32px, right
-- 36px with no nudge; these bring both to 40px from their accent lines.
local NAME1_NUDGE = 0.0030
local NAME2_NUDGE = -0.0015

-- Gotham is proportional, so counting characters and multiplying by one average
-- width is too crude: a space is roughly 40% of an average character and "l"/"i"
-- about 45%, while "W"/"M" run 35% over. Treating them all as equal made
-- "Venom Rebels" (which contains a space) measure WIDER than it really is and
-- "Opponent" (which ends in a narrow "t") measure NARROWER — and because the two
-- names sit on opposite edges, those two errors push in opposite directions.
-- Net effect: Venom Rebels drifted away from its edge while Opponent crept
-- toward its own. Weighting the characters removes most of that.
local CHAR_W = {
  [" "] = 0.42,
  ["i"] = 0.45, ["l"] = 0.45, ["I"] = 0.45, ["j"] = 0.45,
  ["."] = 0.45, [","] = 0.45, ["'"] = 0.45, ["!"] = 0.45, [":"] = 0.45, [";"] = 0.45,
  ["f"] = 0.60, ["t"] = 0.60, ["r"] = 0.60,
  ["W"] = 1.35, ["M"] = 1.35, ["m"] = 1.35, ["w"] = 1.35,
}

local function nameWidth(str)
  local units = 0
  for i = 1, #str do
    local c = str:sub(i, i)
    units = units + (CHAR_W[c] or 1.0)
  end
  return units * NAME_CHAR_W
end

-- The old note above about Text+ ignoring anchors no longer holds in Resolve
-- 21: HorizontalLeftCenterRight (-1 left / 1 right) set from a script works.
-- So each name is anchored on its OUTER edge — the gap to the end of the bar
-- is exact whatever the name, with no width guessing. nameWidth() is now only
-- used by checkName's "too long" warning.
-- Team 1 logo lookup ------------------------------------------------------
local function slug(s)
  return (s:lower():gsub("[^%w]+", "-"):gsub("^%-+", ""):gsub("%-+$", ""))
end
-- Logo lookup (2026-10-02, both teams): team-logos\<club>.png matches any name
-- that STARTS with the club's words — "thundercats.png" serves "Thundercats
-- Polar 14U" — and team-logos\aliases.txt ("tvc = toronto-volleyball-club",
-- one per line) covers nicknames. Same rules as make-bookends.py logo_for().
local function fileExists(f) local fh = io.open(f, "rb") if fh then fh:close() return true end return false end
local function logoFor(name)
  local s = slug(name or ""):gsub("^the%-", "")
  if s == "" then return nil end
  local stems = {}
  pcall(function()
    for _, e in pairs(bmd.readdir(LOGO_DIR .. "*.png") or {}) do
      local n = type(e) == "table" and (e.Name or e[1]) or nil
      if n and not e.IsDir then stems[#stems + 1] = n:lower():gsub("%.png$", "") end
    end
  end)
  local fh = io.open(LOGO_DIR .. "aliases.txt", "r")
  if fh then
    for line in fh:lines() do
      local a, b = line:match("^%s*([^=#]-)%s*=%s*(.-)%s*$")
      if a and b and a ~= "" then
        local as = slug(a):gsub("^the%-", "")
        if s == as or s:sub(1, #as + 1) == as .. "-" then
          if fileExists(LOGO_DIR .. slug(b) .. ".png") then fh:close() return LOGO_DIR .. slug(b) .. ".png" end
        end
      end
    end
    fh:close()
  end
  if fileExists(LOGO_DIR .. s .. ".png") then return LOGO_DIR .. s .. ".png" end
  local best
  for _, st in ipairs(stems) do
    if (s == st or s:sub(1, #st + 1) == st .. "-") and (not best or #st > #best) then best = st end
  end
  return best and (LOGO_DIR .. best .. ".png") or nil
end
local LOGO_FILE = logoFor(TEAM1_NAME)
local HAS_LOGO = LOGO_FILE ~= nil
local LOGO2_FILE = rawget(_G, "SCOREBOARD_NO_LOGO2") and nil or logoFor(TEAM2_NAME)
local HAS_LOGO2 = LOGO2_FILE ~= nil

local FRAME_W, FRAME_H = 3840, 2160
pcall(function()
  FRAME_W = comp:GetPrefs("Comp.FrameFormat.Width")  or FRAME_W
  FRAME_H = comp:GetPrefs("Comp.FrameFormat.Height") or FRAME_H
end)
-- Bar height is 0.115 of frame HEIGHT; the logo is LOGO_H of that, in pixels,
-- then converted to a fraction of frame WIDTH for horizontal layout.
local LOGO_PX = LOGO_H * 0.115 * FRAME_H
local LOGO_W  = LOGO_PX / FRAME_W
-- How far the Team 1 name moves inward when there's a logo (apply-match.lua
-- reads the same number back off the Team1Logo merge, see below).
local LOGO_SHIFT = HAS_LOGO and (LOGO_START + LOGO_W + LOGO_GAP - NAME_MARGIN) or 0
-- Team 2 logo (2026-10-02): mirror image of Team 1's, at the right end of the bar
local LOGO2_SHIFT = HAS_LOGO2 and (LOGO_START + LOGO_W + LOGO_GAP - NAME_MARGIN) or 0

local function nameAnchor(side)
  if side == "left" then return BAR_L + NAME_MARGIN + LOGO_SHIFT + NAME1_NUDGE end
  return BAR_R - NAME_MARGIN - LOGO2_SHIFT + NAME2_NUDGE
end

local function nameCentre(str, side)   -- estimated visual centre, for checkName
  local w = nameWidth(str)
  if side == "left" then return nameAnchor(side) + w / 2 end
  return nameAnchor(side) - w / 2
end

-- Gotham is proportional, so a per-character average is an approximation —
-- a name full of W's and M's runs wide, one full of I's and L's runs narrow.
-- Warn if a name is long enough to reach the serve ball at 0.365 / 0.635.
local function checkName(str, side)
  local w = nameWidth(str)
  local inner = (side == "left") and (nameCentre(str, side) + w / 2)
                                 or  (nameCentre(str, side) - w / 2)
  -- 0.341 / 0.659 = same limit as NAME_MAX_W in apply-match (ball moved out 2026-09-27)
  if (side == "left" and inner > 0.341) or (side == "right" and inner < 0.659) then
    warn(string.format("Team name %q is long enough to crowd the serve ball. "
      .. "Shorten it, or drop NAME_SIZE / switch FONT to \"Gotham Narrow\".", str))
  end
end

checkName(TEAM1_NAME, "left")
checkName(TEAM2_NAME, "right")

local name1 = text("Team1Name", TEAM1_NAME, NAME_SIZE, WHITE, 1.0,
                   nameAnchor("left"),  0.115, COL + 7, ROW + 2)
if name1 then
  setv(name1, "HorizontalLeftCenterRight", -1)   -- anchor on left edge
  setv(name1, "Font", NAME_FONT)
  setv(name1, "Style", NAME_FONT_STYLE)
end
place(name1)
local name2 = text("Team2Name", TEAM2_NAME, NAME_SIZE, WHITE, 1.0,
                   nameAnchor("right"), 0.115, COL + 8, ROW + 2)
if name2 then
  setv(name2, "HorizontalLeftCenterRight", 1)    -- anchor on right edge
  setv(name2, "Font", NAME_FONT)
  setv(name2, "Style", NAME_FONT_STYLE)
end
place(name2)

-- SETS caption sits at 0.139 with the count at 0.101. The walkthrough's
-- 0.132 / 0.106 left only a hairline of air between the caption and the
-- number below it, which read as cramped rather than as a pair.
-- 2026-10-21 (Kenny): "SETS" was too thin to read on a phone. Now Bold, full
-- white, 20% larger (was SemiBold, alpha 0.45, size 0.016, spacing 1.25).
-- Still clears the set-win box below it (checked on a real frame).
local SETS_LABEL = { size = 0.0192, alpha = 1.0, style = "Bold", spacing = 1.18 }
local function setsLabel(name, x, col)
  local l = text(name, "SETS", SETS_LABEL.size, WHITE, SETS_LABEL.alpha, x, 0.139, col, ROW + 2)
  setv(l, "Style", SETS_LABEL.style)
  setv(l, "CharacterSpacing", SETS_LABEL.spacing)
  place(l)
end
setsLabel("Team1SetsLabel", 0.406, COL + 9)

-- 2026-10-14 (Kenny): rounded box in the team colour behind the SETS number,
-- shown only for a moment when that team wins a set (apply-match.lua keys the
-- merge's Blend; 0 = hidden). Sized to the number at its 1.18x pop, centred on
-- the digit glyph (0.0972, a little below the Text+ centre), clear of "SETS".
local SETS_CHIP = { w = 0.0239, h = 0.0493, y = 0.0972, r = 0.375, level = 0.92 }
place(plate("Team1SetsChip", GREEN, SETS_CHIP.level,
      { w = SETS_CHIP.w, h = SETS_CHIP.h, x = 0.406, y = SETS_CHIP.y, r = SETS_CHIP.r }, COL + 10, ROW + 2),
      "Team1SetsChipMerge", 0)
place(text("Team1Sets", "0", 0.043, WHITE, 1.0, 0.406, 0.101, COL + 10, ROW + 2), "Team1SetsMerge")

setsLabel("Team2SetsLabel", 0.594, COL + 11)

place(plate("Team2SetsChip", BLUE, SETS_CHIP.level,
      { w = SETS_CHIP.w, h = SETS_CHIP.h, x = 0.594, y = SETS_CHIP.y, r = SETS_CHIP.r }, COL + 11, ROW + 2),
      "Team2SetsChipMerge", 0)

-- Merges are named so apply-match.lua can fade them (set-change dip).
place(text("Team2Sets",  "0", 0.043, WHITE, 1.0, 0.594, 0.101, COL + 12, ROW + 2), "Team2SetsMerge")
place(text("Team1Score", "0", 0.076, WHITE, 1.0, 0.466, 0.115, COL + 13, ROW + 2), "Team1ScoreMerge")
place(text("Team2Score", "0", 0.076, WHITE, 1.0, 0.534, 0.115, COL + 14, ROW + 2), "Team2ScoreMerge")

-- Step 6 — serve balls -----------------------------------------------------
-- The Loader is named Team1Serve / Team2Serve (per the spec), but the thing
-- that actually animates is the MERGE's Blend — so the merges get the
-- predictable names Team1ServeMerge / Team2ServeMerge. Phase-2 drives those.
local function serveBall(name, col)
  local ld = add("Loader", name, col, ROW + 3)
  if not ld then return nil end
  pcall(function() ld.Clip[1] = SERVE_ICON_PATH end)

  local tr = add("Transform", name .. "Xf", col, ROW + 2)
  if not tr then return ld end
  tr.Input = ld.Output
  -- A Transform's Size is relative to the SOURCE image, not the frame. The PNG
  -- is 512px, so the walkthrough's 0.02 rendered a 10px dot. See SERVE_SIZE.
  setv(tr, "Size", SERVE_SIZE)
  childOf[tr] = ld
  return tr
end

-- Position the ball on the MERGE, not on the Transform.
-- The Loader outputs a 512x512 image, so everything downstream of it works on a
-- 512x512 canvas. Setting the Transform's Center only moves the ball around
-- inside that small canvas; the Merge then drops the whole canvas at frame
-- centre, which is why the ball appeared near the middle of the picture instead
-- of on the bar. A Merge's Center IS in frame coordinates, so it goes here.
-- 2026-10-21 (Kenny, option A): the ball sat ~4px (finished 4K) above the centre
-- of the team-name capitals; -0.0025 (x 2160 x OVERALL_SIZE 0.75 = 4px) centres it.
local SERVE_Y_NUDGE = -0.0025
local function serveAt(mergeName, cx)
  local m = comp:FindTool(mergeName)
  if m then setPoint(m, "Center", cx, SYp(0.115 + SERVE_Y_NUDGE)) end
end

-- Nudged 5px further from the name/sets dividers at 0.379 / 0.621 — so the left
-- ball moves left and the right ball moves right, away from its own divider.
-- These coordinates are applied BEFORE the MasterSize Transform, so 5 finished
-- pixels is 5 / (3840 * OVERALL_SIZE) = 0.00186, not 5 / 3840.
-- 2026-09-27 (Kenny): ball sat too close to the SETS divider line. Moved
-- further out so it's centred between the name limit (0.341) and the divider
-- (0.379): SERVE_X = 0.3598 (was 0.3631), right side mirrored.
-- apply-match.lua NAME_MAX_W keeps names clear of it.
local SERVE_X = rawget(_G, "SCOREBOARD_SERVE_X") or 0.3598
place(serveBall("Team1Serve", COL + 15), "Team1ServeMerge", 0.0)
serveAt("Team1ServeMerge", SERVE_X)

place(serveBall("Team2Serve", COL + 16), "Team2ServeMerge", 0.0)
serveAt("Team2ServeMerge", 1 - SERVE_X)

-- Team 1 logo (only if a logo file exists for this team) -------------------
-- Same Loader -> Transform -> Merge pattern as the serve balls: Size on the
-- Transform is relative to the source PNG, position goes on the Merge.
-- 2026-10-21 (Kenny): every logo must LOOK the same size. Size each logo by its
-- visible drawing (team-logos\_logo-ink.txt, written by logo_sizes.py before the
-- build) instead of its canvas, times an optional optical factor from
-- team-logos\logo-sizes.txt. A logo too wide for its slot is capped at the slot
-- width so names never move. No table entry -> the old canvas sizing.
local LOGO_INK_H = 0.6334   -- visible height as a fraction of the bar (= 118 px on the 4K frame)
local function logoFit(file, srcPx)
  local stem = (file:match("([^/\\]+)%.[Pp][Nn][Gg]$") or ""):lower()
  local fh = io.open(LOGO_DIR .. "_logo-ink.txt", "r")
  if fh then
    for line in fh:lines() do
      local k, W, H, x0, y0, x1, y1, f = line:match("^(%S+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+([%d%.]+)")
      if k == stem then
        fh:close()
        W, H, x0, y0, x1, y1, f = tonumber(W), tonumber(H), tonumber(x0), tonumber(y0), tonumber(x1), tonumber(y1), tonumber(f)
        local s = LOGO_INK_H * 0.115 * FRAME_H * f / math.max(1, y1 - y0)
        if (x1 - x0) * s > LOGO_PX then s = LOGO_PX / math.max(1, x1 - x0) end
        local dx = -((x0 + x1) / 2 - W / 2) * s / FRAME_W
        local dy = ((y0 + y1) / 2 - H / 2) * s / FRAME_H
        print(string.format(" logo %s: drawn %.0f px tall on the 4K frame (factor %.2f)", stem, (y1 - y0) * s * OVERALL_SIZE * 2160 / FRAME_H, f))
        return s, dx, dy
      end
    end
    fh:close()
  end
  return LOGO_PX / srcPx, 0, 0
end

if HAS_LOGO then
  local ld = add("Loader", "Team1LogoFile", COL + 16, ROW + 3)
  if ld then
    pcall(function() ld.Clip[1] = (LOGO_FILE:gsub("/", "\\")) end)
    local srcPx = 600
    pcall(function()
      local a = ld:GetAttrs()
      srcPx = (a.TOOLIT_Clip_Height and a.TOOLIT_Clip_Height[1]) or srcPx
    end)
    local tr = add("Transform", "Team1LogoXf", COL + 16, ROW + 2)
    if tr then
      tr.Input = ld.Output
      local ls, ldx, ldy = logoFit(LOGO_FILE, srcPx)
      setv(tr, "Size", ls)
      childOf[tr] = ld
      place(tr, "Team1Logo")
      local m = comp:FindTool("Team1Logo")
      if m then setPoint(m, "Center", BAR_L + LOGO_START + LOGO_W / 2 + ldx, SYp(0.115 + ldy)) end
    end
  end
end
if HAS_LOGO2 then
  local ld = add("Loader", "Team2LogoFile", COL + 17, ROW + 3)
  if ld then
    pcall(function() ld.Clip[1] = (LOGO2_FILE:gsub("/", "\\")) end)
    local srcPx = 600
    pcall(function()
      local a = ld:GetAttrs()
      srcPx = (a.TOOLIT_Clip_Height and a.TOOLIT_Clip_Height[1]) or srcPx
    end)
    local tr = add("Transform", "Team2LogoXf", COL + 17, ROW + 2)
    if tr then
      tr.Input = ld.Output
      local ls, ldx, ldy = logoFit(LOGO2_FILE, srcPx)
      setv(tr, "Size", ls)
      childOf[tr] = ld
      place(tr, "Team2Logo")
      local m = comp:FindTool("Team2Logo")
      if m then setPoint(m, "Center", BAR_R - LOGO_START - LOGO_W / 2 + ldx, SYp(0.115 + ldy)) end
    end
  end
end

-- SET POINT / MATCH POINT tags (approved 2026-09-26, style "text") ---------
-- One tag per team, on the same row as the SET pill, lined up with the outer
-- end of that team's cell. Both start hidden (merge Blend 0); apply-match.lua
-- keyframes Team{n}TagBGMerge / Team{n}TagMerge Blend on and off, and the
-- Team{n}Tag text between "SET POINT" and "MATCH POINT", from the match data.
--   "text"   dark pill like SET n, words in the team colour   <- chosen (B)
--   "accent" dark pill, white words, team-colour stripe at the outer end (A)
--   "deep"   darker shade of the team colour, white words (C)
--   "solid"  team-colour pill, black/white words (first try, rejected)
-- TAG_PREVIEW = { side = 1|2, text = "...", style = "..." } forces one tag
-- visible for a design preview; normal runs leave it nil.
-- Mask helpers for the "tab" style ------------------------------------------
-- A tab is a rectangle that starts TAB_EXT inside the bar and has the bar's own
-- shape subtracted, so it meets the bar exactly (no overlap = no darker seam,
-- and its bottom corners are hidden). The outline is built the same way:
-- (shapes grown by OUTLINE_PX) minus (the shapes themselves).
local BAR_RECT = { w = BAR_WIDTH, h = 0.115, x = 0.5, y = 0.115, r = 0.5 }
local function rmask(name, rect, level, col, row)
  local m = add("RectangleMask", name, col, row)
  if not m then return nil end
  canvas(m, true)
  setv(m, "Level",  level or 1.0)
  setv(m, "Width",  rect.w)
  setv(m, "Height", SH(rect.h))
  setPoint(m, "Center", rect.x, SYp(rect.y))
  setv(m, "CornerRadius", rect.r or 0)
  return m
end
local function chainMask(prev, m, mode)
  if not (prev and m) then return m end
  pcall(function() m:ConnectInput("EffectMask", prev) end)
  local ok = pcall(function() m.PaintMode[0] = mode end)
  if not ok then pcall(function() m:SetInput("PaintMode", mode, 0) end) end
  return m
end
local function maskedPlate(name, colour, maskTool, col, row)
  local bg = add("Background", name, col, row)
  if not bg then return nil end
  setv(bg, "TopLeftRed", colour[1]) setv(bg, "TopLeftGreen", colour[2]) setv(bg, "TopLeftBlue", colour[3])
  setv(bg, "TopLeftAlpha", 1.0)
  canvas(bg)
  pcall(function() bg:ConnectInput("EffectMask", maskTool) end)
  childOf[bg] = maskTool
  return bg
end
local function tabRect(cx, w, h, r)   -- the tab's rectangle, extended into the bar
  return { w = w, h = h + TAB_EXT, x = cx, y = BAR_TOP + (h - TAB_EXT) / 2, r = r }
end
local function shrink(rect)
  local dw = OUTLINE_PX / (FRAME_W * OVERALL_SIZE)
  local dh = OUTLINE_PX / (FRAME_H * OVERALL_SIZE)
  return { w = rect.w - 2 * dw, h = rect.h - 2 * dh, x = rect.x, y = rect.y, r = rect.r }
end
local function grow(rect)
  local dw = OUTLINE_PX / (FRAME_W * OVERALL_SIZE)
  local dh = OUTLINE_PX / (FRAME_H * OVERALL_SIZE)
  return { w = rect.w + 2 * dw, h = rect.h + 2 * dh, x = rect.x, y = rect.y, r = rect.r }
end
local function tabPlate(name, colour, alpha, cx, w, h, r, col, row)
  local a = rmask(name .. "Shape", tabRect(cx, w, h, r), alpha, col, row - 1)
  local b = chainMask(a, rmask(name .. "Cut", BAR_RECT, 1.0, col, row - 2), "Subtract")
  return maskedPlate(name, colour, b, col, row)
end

local function makeTag(side)
  local TAG_TEXT = 0.026
  local TAG_W, TAG_H = 0.150, 0.029 * 2   -- wide enough for "MATCH POINT"
  local tagY = PILL_ABOVE and (0.115 + 0.0575 + 0.008 + 0.029) or 0.022
  local tagR = 0.5
  if PILL_STYLE == "clean" then
    TAG_TEXT, TAG_H = 0.025, 0.052
    tagY = BAR_TOP + 0.008 + TAG_H / 2
  elseif PILL_STYLE == "tab" then
    -- Kenny, 2026-09-27: joined-on tags didn't look right — they FLOAT, with
    -- their top lined up with the top of the SET tab.
    TAG_TEXT, TAG_H = 0.024, TAB_H - 0.008
    tagY = BAR_TOP + 0.008 + TAG_H / 2
  end
  local x = (side == 1) and (BAR_L + LOGO_START + TAG_W / 2) or (BAR_R - LOGO_START - TAG_W / 2)
  local team = (side == 1) and GREEN or BLUE
  local pv = (type(TAG_PREVIEW) == "table") and TAG_PREVIEW or nil
  local style = (pv and pv.style) or TAG_STYLE
  local shown = (pv and ((pv.side == 2) and 2 or 1) == side) and 1.0 or 0.0
  local label = (pv and pv.text) or "SET POINT"

  local bgCol, bgA, txtCol = BLACK, 0.74, WHITE
  if style == "solid" then bgCol, bgA, txtCol = team, 1.0, (side == 1) and BLACK or WHITE
  elseif style == "text" then
    -- The club blue (#0A84FF) is too dark to read as small text on the dark
    -- pill (Kenny, 2026-09-26), so the opponent's words use a lighter sky blue.
    txtCol = (side == 1) and GREEN or TAG_TEXT_BLUE
    if pv and pv.rgb and ((pv.side == 2) and 2 or 1) == side then txtCol = pv.rgb end
  elseif style == "deep" then bgCol, bgA = { team[1] * 0.50, team[2] * 0.50, team[3] * 0.50 }, 0.95 end

  local pre = "Team" .. side .. "Tag"
  place(plate(pre .. "BG", bgCol, bgA, { w = TAG_W, h = TAG_H, x = x, y = tagY, r = tagR },
        COL + 17, ROW + 4), pre .. "BGMerge", shown)
  local tx = x
  if style == "accent" then
    local ax = (side == 1) and (x - TAG_W / 2 + 0.0095) or (x + TAG_W / 2 - 0.0095)
    place(plate(pre .. "Accent", team, 1.0, { w = 0.0016, h = 0.030, x = ax, y = tagY, r = 1.0 },
          COL + 17, ROW + 6), pre .. "AccentMerge", shown)
    tx = x + ((side == 1) and 0.005 or -0.005)
  end
  local tg = text(pre, label, TAG_TEXT, txtCol, 1.0, tx, tagY + TAG_TEXT * 0.118, COL + 18, ROW + 4)
  setv(tg, "Style", "Bold")
  setv(tg, "CharacterSpacing", (PILL_STYLE == "float") and 1.15 or 1.06)
  place(tg, pre .. "Merge", shown)
end
if SHOW_POINT_TAGS then makeTag(1) makeTag(2) end

-- Step 7 — set pill --------------------------------------------------------
-- Pill grown from 0.05 x 0.024 to 0.075 x 0.034, with the text up from 0.014
-- to 0.017. The height/text ratio goes 1.7 -> 2.0, so the text sits inside a
-- ring of padding rather than filling the pill edge to edge.
-- Y dropped 0.038 -> 0.030 to keep the taller pill clear of the bar above it.
-- Corner radius 0.50 to match the bar, down from the full-pill 1.0.
-- Note this is a RELATIVE value: 1.0 means "as round as this shape can go",
-- i.e. radius = half the short side. Because the pill is 0.034 tall and the bar
-- is 0.115, the same 0.50 gives the same *proportional* roundness but a smaller
-- absolute radius. Matching the bar's absolute radius isn't possible here —
-- it's larger than the pill's own half-height, so it would clamp back to 1.0.
-- SET n text raised from 0.017 to 0.022, i.e. just under the team names at
-- NAME_SIZE 0.026. The pill grows with it rather than staying put: at the old
-- 0.075 x 0.034 the bigger text would have filled it edge to edge, losing the
-- padding ring. Height stays at 2x the text size and the width scales to match,
-- and the whole thing drops 0.004 to keep clear of the bar above it.
local PILL_TEXT = 0.029   -- Barlow Condensed (was 0.022 with Gotham)
local PILL_Y    = 0.022   -- lowered from 0.026 so the taller Barlow pill clears the bar
-- 2026-09-26: above the bar instead (bar top 0.1725 + 0.008 gap + half pill),
-- so it's clear of YouTube's player controls. See BAR_RAISE / PILL_ABOVE.
if PILL_ABOVE then PILL_Y = 0.115 + 0.0575 + 0.008 + PILL_TEXT end

local pillW, pillH, pillR, pillCol, pillA = 0.097, PILL_TEXT * 2, 0.50, BLACK, 0.74
local pillTxt, pillTrack, pillTxtA, pillBold = PILL_TEXT, 1.20, 0.70, false
if PILL_STYLE == "clean" then
  -- Snug pill, text at normal-ish tracking, bold and near-white: reads as a
  -- label rather than a spaced-out caption.
  pillTxt, pillTrack, pillTxtA, pillBold = 0.025, 1.06, 0.95, true
  pillW, pillH = 0.080, 0.052
  PILL_Y = BAR_TOP + 0.008 + pillH / 2
elseif PILL_STYLE == "tab" then
  -- Joined to the bar above the grey score cell (0.134 wide), same grey, so
  -- the score box looks like one piece with a header. Small corner radius so
  -- the bottom corners meet the bar cleanly.
  -- 2026-10-21 (Kenny): "SET n" 10% larger (0.025 -> 0.0275), still well inside the tab.
  pillTxt, pillTrack, pillTxtA, pillBold = 0.0275, 1.08, 0.95, true
  -- Width = score cell (0.134) minus one outline width, so the outline drawn
  -- just outside the tab lands exactly on the separators at 0.433 / 0.567.
  -- Width = score cell (0.134) PLUS one line width: the outline is drawn just
  -- INSIDE the edge, so it lands exactly on the separators at 0.433 / 0.567.
  pillW, pillH, pillR, pillCol, pillA = 0.134 + 0.0008, TAB_H, 0.2, TAB_GREY, TAB_ALPHA
  PILL_Y = BAR_TOP + pillH / 2
end

if PILL_STYLE == "tab" then
  place(tabPlate("PillBG", pillCol, pillA, 0.5, pillW, pillH, pillR, COL + 17, ROW + 2))
  if OUTLINE then
    -- One outline around bar + SET tab together: (bar grown) max (tab grown),
    -- minus bar, minus tab. No line where the tab joins the bar.
    local tr = tabRect(0.5, pillW, pillH, pillR)
    -- 2026-09-27: the line is now drawn just INSIDE the edge (shape minus the
    -- shape shrunk by one line width). Outside the edge it sat over the video,
    -- so it looked brighter/different from the cell separators, which sit on
    -- the dark bar. Inside, both are white 0.16 over the same dark background.
    local m = rmask("OutlineA", BAR_RECT, OUTLINE_ALPHA, COL + 20, ROW + 3)
    m = chainMask(m, rmask("OutlineB", tr, OUTLINE_ALPHA, COL + 20, ROW + 4), "Maximum")
    m = chainMask(m, rmask("OutlineC", shrink(BAR_RECT), 1.0, COL + 20, ROW + 5), "Subtract")
    m = chainMask(m, rmask("OutlineD", shrink(tr), 1.0, COL + 20, ROW + 6), "Subtract")
    place(maskedPlate("BarOutline", WHITE, m, COL + 20, ROW + 2))
  end
else
  place(plate("PillBG", pillCol, pillA,
        { w = pillW, h = pillH, x = 0.5, y = PILL_Y, r = pillR }, COL + 17, ROW + 2))
end

-- Text sits a touch above the pill's centre. Text+ centres on the font's full
-- em box (ascender to descender), but "SET 1" is all caps with no descenders,
-- so centring the box leaves the visible glyphs low. This nudge optically
-- centres the caps instead of the box.
local pillText = text("SetNumber", "SET 1", pillTxt, WHITE, pillTxtA,
                      0.5, PILL_Y + pillTxt * 0.118, COL + 18, ROW + 2)
if pillBold then setv(pillText, "Style", "Bold") end
-- NOTE: in Text+ CharacterSpacing is a MULTIPLIER (1.0 = normal).
setv(pillText, "CharacterSpacing", pillTrack)
place(pillText, "SetNumberMerge")

-- Shadow as a plate (see SHADOW_MODE). Offset/softness are given AFTER the
-- 0.70 MasterSize scale in the Shadow-tool version, so divide by it here.
if SHADOW_MODE == "plate" then
  local dy = 0.010 / OVERALL_SIZE
  local m = rmask("ShadowBarShape", { w = BAR_WIDTH, h = 0.115, x = 0.5, y = 0.115 - dy, r = 0.5 },
                  SHADOW_LEVEL, COL + 22, ROW + 3)
  setv(m, "SoftEdge", SHADOW_EDGE)
  if PILL_STYLE == "tab" then
    local tr = tabRect(0.5, pillW, pillH, pillR)
    tr.y = tr.y - dy
    local m2 = rmask("ShadowTabShape", tr, SHADOW_LEVEL, COL + 22, ROW + 4)
    setv(m2, "SoftEdge", SHADOW_EDGE)
    m = chainMask(m, m2, "Maximum")
  end
  local sp = maskedPlate("ShadowPlate", BLACK, m, COL + 22, ROW + 2)
  local sm = add("Merge", "ShadowUnder", COL + 22, ROW)
  if sp and sm then
    sm.Background = sp.Output    -- shadow underneath ...
    sm.Foreground = top.Output   -- ... everything built so far on top
    top = sm
  end
end

-- Step 9 — master size dial (before the shadow, per the guide) -------------
local master = add("Transform", "MasterSize", COL + 19, ROW)
if master then
  master.Input = top.Output
  setv(master, "Size", OVERALL_SIZE)
  -- Scale about the bar's own centre, not the frame centre — otherwise shrinking
  -- the bar also lifts it up toward the middle of the picture.
  -- NOTE: on a Transform, Center is the image's POSITION; the scale anchor is
  -- Pivot. Setting Center here moves the whole comp off the bottom of frame.
  setPoint(master, "Pivot", 0.5, SYp(0.115))
  -- Lift the finished bar clear of YouTube's player controls (see BAR_RAISE).
  -- Center is the image's position, so moving it up moves everything.
  -- On the strip the raise is applied by the final placement merge instead.
  setPoint(master, "Center", 0.5, STRIP and 0.5 or (0.5 + BAR_RAISE))
  top = master
end

-- Step 8 — drop shadow -----------------------------------------------------
local shadow = (SHADOW_MODE == "tool") and add("Shadow", "BarShadow", COL + 20, ROW) or nil
if shadow then
  shadow.Input = top.Output
  -- The input is "Softness", not "ShadowSoftness" — the old name silently did
  -- nothing, and inspecting BarShadow confirmed Softness was still 0, i.e. the
  -- shadow was invisible. ShadowOffset is a point where 0.5,0.5 means "no
  -- offset", so the shadow also needs nudging down to be seen at all.
  -- 2026-09-26 (depth): softer and stronger than the original 4 / 0.45, which
  -- barely registered on a bright floor.
  setv(shadow, "Softness", SHADOW_SOFT)
  setPoint(shadow, "ShadowOffset", 0.5, 0.5 - 0.010 * SY)
  setv(shadow, "Alpha", SHADOW_ALPHA)
  top = shadow
elseif SHADOW_MODE == "tool" then
  warn("Drop Shadow not created — add a 'Drop Shadow' node between the last Merge and MediaOut1 by hand (Softness 16, Opacity 0.45).")
end

-- Whole-scoreboard fade (2026-09-27) --------------------------------------
-- Everything goes through one last Merge over a fully transparent Background;
-- apply-match.lua animates FadeAllMerge's Blend so the scoreboard fades in
-- over the first ~0.5 s of the video and out over the last ~0.5 s.
local clear = add("Background", "ClearBG", COL + 21, ROW + 1)
if clear then
  setv(clear, "UseFrameFormatSettings", 1)
  setv(clear, "TopLeftRed", 0) setv(clear, "TopLeftGreen", 0) setv(clear, "TopLeftBlue", 0)
  setv(clear, "TopLeftAlpha", 0)
  local fm = add("Merge", "FadeAllMerge", COL + 21, ROW)
  if fm then
    fm.Background = clear.Output
    fm.Foreground = top.Output
    -- STRIP: this merge is also what drops the finished strip into the 4K
    -- frame — at the strip's own height, lifted by BAR_RAISE.
    if STRIP then setPoint(fm, "Center", 0.5, STRIP_CENTRE_Y + BAR_RAISE) end
    top = fm
  end
end

-- Connect to output --------------------------------------------------------
if mediaOut then
  mediaOut.Input = top.Output
else
  warn("MediaOut1 not found — connect the last node to your output by hand.")
end

-- Tail of the chain continues the same straight row.
setPos(master,   mergeCount + 1, 0)
setPos(shadow,   mergeCount + 2, 0)
setPos(comp:FindTool("FadeAllMerge"), mergeCount + 3, 0)
setPos(comp:FindTool("ClearBG"),      mergeCount + 3, 1)
setPos(mediaOut, mergeCount + 4, 0)

comp:EndUndo(true)
comp:Unlock()

--------------------------------------------------------------------------------
-- REPORT
--------------------------------------------------------------------------------

print("=====================================================")
print(" Venom Rebels scoreboard built.")
print(string.format(" %d merges, chained left to right.", mergeCount))
print(string.format(" Teams: %s  vs  %s", TEAM1_NAME, TEAM2_NAME))
print(HAS_LOGO and (" Team 1 logo: " .. LOGO_FILE)
               or  (" Team 1 logo: none (no logo for " .. tostring(TEAM1_NAME) .. ")"))   -- 2026-10-09: LOGO_FILE is nil here (non-Venom team 1)
if type(TAG_PREVIEW) == "table" then print(" ** Tag PREVIEW built: " .. tostring(TAG_PREVIEW.text)) end
print("")

if TEAM2_NAME == "Opponent" then
  print(" ** TEAM2_NAME is still the placeholder \"Opponent\".")
  print("    Set it at the top of THIS SCRIPT (not in the Team2Name node) and")
  print("    re-run — the name's position is calculated from the string.")
  print("")
end

if CLEAR_EXISTING then
  print(" ** CLEAR_EXISTING is on: this run deleted and rebuilt the whole graph.")
  print("    Set it to false once the phase-2 script has written keyframes,")
  print("    otherwise the next run will wipe them.")
  print("")
end

print(" If a serve ball is missing, check the icon is still at:")
print("   " .. SERVE_ICON_PATH)

if #warnings > 0 then
  print("")
  print(" Notes:")
  for _, w in ipairs(warnings) do print("   - " .. w) end
end
print("=====================================================")
