// preview only: a stand-in "gym" plate under the transparent graphics (the workflow never shows it)
(function () {
  if (!VM.q.get("p")) return;
  const el = document.getElementById("plate");
  const A = "radial-gradient(120% 80% at 50% 108%, #c9a271 0%, #a67c4f 34%, #5d4630 62%, #23262b 63%, #3a4048 100%)";
  const B = "radial-gradient(120% 80% at 38% 108%, #cfa978 0%, #ad8455 34%, #624a33 62%, #1f2227 63%, #343a43 100%)";
  el.style.background = A;
  el.insertAdjacentHTML("beforeend", '<div style="position:absolute;left:0;right:0;top:66.5%;height:3px;background:rgba(255,255,255,.5)"></div><div id="plateTag" style="position:absolute;left:60px;top:48px;font:700 26px Barlow Condensed;letter-spacing:.14em;color:rgba(255,255,255,.55)">STAND-IN FOR MATCH FOOTAGE</div>');
  window.__plate = which => { el.style.background = which ? B : A; };
})();
