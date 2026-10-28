--[[
================================================================================
 Volleyball Autopilot scoreboard — build + apply, one command
================================================================================

 Runs build-scoreboard.lua then apply-match.lua back to back, so putting the
 overlay on a match is one Console line instead of two:

   dofile("C:/Users/YOURNAME/scoreboard-pipeline/run-overlay.lua")

 This is purely a convenience wrapper — it doesn't change what either script
 does, and each one still works fine run on its own (e.g. re-applying a
 corrected match file later without rebuilding the graph:
 dofile(".../apply-match.lua") by itself).

 If Step 1 prints an ERROR (not just a warning), stop and fix that before
 trusting anything Step 2 reports — it will still run against whatever nodes
 exist, but a failed build means there's nothing for it to write onto.
================================================================================
--]]

local BASE = "C:/Users/YOURNAME/scoreboard-pipeline/"

print("=====================================================")
print(" Step 1 of 2 — building the scoreboard graph")
print("=====================================================")
dofile(BASE .. "build-scoreboard.lua")

print("")
print("=====================================================")
print(" Step 2 of 2 — applying match data")
print("=====================================================")
dofile(BASE .. "apply-match.lua")

print("")
print("Done. Scroll up through both sections for any *** warnings before")
print("trusting the render.")
