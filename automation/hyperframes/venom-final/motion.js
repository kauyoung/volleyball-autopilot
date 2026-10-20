// motion.js — shared motion tokens for the Venom intro and FINAL screens.
// Load AFTER gsap.min.js and CustomEase.min.js, BEFORE the page's own script.
(function () {
  gsap.registerPlugin(CustomEase);
  CustomEase.create("venomOut",    "0.23, 1, 0.32, 1");    // strong ease-out — entrances and exits
  CustomEase.create("venomInOut",  "0.77, 0, 0.175, 1");   // strong ease-in-out — things moving across the screen
  CustomEase.create("venomDrawer", "0.32, 0.72, 0, 1");    // drawer curve — the opening panel wipe (plan 003)
  CustomEase.create("venomEase",   "0.25, 0.1, 0.25, 1");  // CSS "ease" — colour and tint changes (plan 004)
  window.VMotion = {
    OUT: "venomOut",
    IN_OUT: "venomInOut",
    DRAWER: "venomDrawer",
    EASE: "venomEase",
    STAGGER: 0.06,
    ENTER: 0.45,         // how long main elements take to arrive (text, rows, badges, tiles) — Kenny prefers this unhurried pace
    PANEL: 0.55,         // the opening diagonal panel wipe
    TEMPO: 1.7,          // overall pace: 1 = as authored, 1.7 = "relaxed" (Kenny's pick, 2026-10-03)
    INTRO_HOLD: 0.05,     // seconds the finished intro stays still before its exit (real time, not scaled by TEMPO)
    COUNT: 0.8,          // number count-ups on the FINAL screen (seconds)
    CLIP: {
      hideL: "inset(-20% 100% -20% 0%)",
      hideR: "inset(-20% 0% -20% 100%)",
      hideC: "inset(-20% 50% -20% 50%)",
      hideB: "inset(100% 0% 0% 0%)",
      show:  "inset(-20% 0% -20% 0%)",
      showB: "inset(0% 0% 0% 0%)"
    }
  };
})();
