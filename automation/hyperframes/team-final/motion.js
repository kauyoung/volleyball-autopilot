// motion.js (v2, 2026-11-12) - shared motion system for the Home intro, FINAL screen and wipes.
// Load AFTER gsap.min.js + CustomEase.min.js, BEFORE the page's own script.
// One idea everywhere: everything lives ON a 14-degree panel. The panel's edge uncovers the
// content as it sweeps in and wipes it away as it leaves. The colour bands on the edges
// stretch with speed and settle to a thin line.
(function () {
  gsap.registerPlugin(CustomEase);
  CustomEase.create("vOut",    "0.16, 1, 0.3, 1");      // long, soft landing - entrances
  CustomEase.create("vIn",     "0.7, 0, 0.84, 0");      // exits
  CustomEase.create("vInOut",  "0.76, 0, 0.24, 1");     // the panel leaving
  CustomEase.create("vDrawer", "0.32, 0.72, 0, 1");     // the panel arriving
  CustomEase.create("vSoft",   "0.25, 0.1, 0.25, 1");   // colour changes
  const OFF = 2620;                                      // panel fully off screen (px at 1080)
  // #panel clips; #stage inside it gets the exact opposite move, so content stays put on screen
  // (a sideways move and a skewX commute, so the two tweens cancel exactly at every frame).
  function init() {
    gsap.set("#panel, #edges", { x: -OFF, skewX: -14 });
    gsap.set("#stage", { x: OFF, skewX: 14 });
  }
  function panelIn(tl, at, dur) {
    tl.fromTo("#panel, #edges", { x: -OFF }, { x: 0, duration: dur, ease: "vDrawer" }, at)
      .fromTo("#stage", { x: OFF }, { x: 0, duration: dur, ease: "vDrawer" }, at)
      .fromTo("#edges .lead.a", { scaleX: 7 }, { scaleX: 1, duration: dur, ease: "vOut" }, at)
      .fromTo("#edges .lead.b", { scaleX: 22, opacity: 0.55 }, { scaleX: 1, opacity: 0, duration: dur * 0.95, ease: "vOut" }, at);
  }
  function panelOut(tl, at, dur) {
    tl.fromTo("#panel, #edges", { x: 0 }, { x: OFF, duration: dur, ease: "vInOut", immediateRender: false }, at)
      .fromTo("#stage", { x: 0 }, { x: -OFF, duration: dur, ease: "vInOut", immediateRender: false }, at)
      .fromTo("#edges .trail.a", { scaleX: 1 }, { scaleX: 10, duration: dur * 0.6, ease: "power2.in", immediateRender: false }, at)
      .fromTo("#edges .trail.b", { scaleX: 1, opacity: 0 }, { scaleX: 22, opacity: 0.55, duration: dur * 0.6, ease: "power2.in", immediateRender: false }, at);
  }
  // preview only (never used by the workflow): index.html?p=1 draws at 1920x1080 over a stand-in plate
  const q = new URLSearchParams(location.search);
  if (q.get("p")) document.documentElement.classList.add("preview");
  window.VM = { OUT: "vOut", IN: "vIn", IN_OUT: "vInOut", DRAWER: "vDrawer", SOFT: "vSoft", OFF, init, panelIn, panelOut, q,
    count(tl, el, at, dur) {       // whole-number count-up that decelerates onto the value
      tl.to(el, { textContent: +el.dataset.to, snap: { textContent: 1 }, duration: dur || 0.9, ease: "vOut" }, at);
    } };
})();
