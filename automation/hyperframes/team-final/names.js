// ================= TEAM-NAME RULES (shared by intro + FINAL summary) =================
// Layout: CLUB big on line 1 · TEAM + AGE GROUP smaller on line 2.
// How the club/team split is decided (first match wins):
//   1. Exact-name override from intro-names.txt  ("Riverside Rapids = Riverside | Rapids 14U")
//   2. A "|" typed in the name                   ("Mississauga | Mavericks 13U")
//   3. A natural separator typed in the name      ("Durham Attack - Gold U14", "X: Y")
//   4. Known club list, longest match first       ("Durham Attack" beats "Durham");
//      singular/plural typed either way still matches; "Volleyball/Club/VC" typed right
//      after the club is dropped ("Reach Volleyball Club Elites 14U" → REACH / ELITES 14U);
//      the big line always uses the list's spelling
//   5. Unknown club: everything before the age group is big, the age group is small
//   6. No age group either: the whole name is big, no second line
// Typing clean-up first: extra spaces, stray punctuation, "14 U"/"14-u"/"Under 14" → "14U",
//   "U 14" → "U14"; matching ignores capitals and accents. Blank name → "OPPONENT".
// Long club names break onto two big lines by rules: no age tag or 1–2 letter word alone ·
//   line 1 never ends on of/the/&/de/la/St… · "Club/Academy/Association" stays with the word
//   before it · biggest text wins, then the more even pair of lines.
// Needs two hidden spans in the page: #measure (big-line font) and #measure2 (second-line font).
(function () {
  let MAXW = 620; const ONE_MAX = 96, ONE_MIN = 62, TWO_MAX = 72, TWO_MIN = 44, SUB_MAX = 62, SUB_MIN = 36;
  const AGE  = /^(U\d{1,2}|\d{1,2}U)$/i;
  const GLUE = /^(U?\d{1,2}U?|\d+(ST|ND|RD|TH)?|[IVX]{1,4}|[A-Z]|JR\.?|SR\.?|#\d+)$/i;
  const JOIN = /^(OF|THE|&|AND|DE|DU|DES|LA|LE|LES|ST\.?|STE\.?|AT|IN|FOR|ET)$/i;
  const ORG  = /^(CLUB|ACADEMY|ASSOCIATION|ASSOC\.?|VC|VBC|SC)$/i;
  const FILLER = /^(VOLLEYBALL|VOLLEY|VB|CLUB|VC|VBC|ACADEMY|ASSOCIATION)$/i;

  const fold = t => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/\s+/g, " ").trim();
  function clean(t) {
    t = String(t || "").replace(/[–—]/g, "-").replace(/\s+/g, " ").trim();
    t = t.replace(/^[\s\-:,.|]+|[\s\-:,.|]+$/g, "");
    t = t.replace(/\s+-\s+|\s*:\s+/g, " | ");                       // "A - B", "A: B" → "A | B"
    t = t.replace(/\bunder\s*-?\s*(\d{1,2})\b/gi, "$1U")
         .replace(/\b(\d{1,2})\s*-?\s*u\b/gi, "$1U")
         .replace(/\bu\s*-?\s*(\d{1,2})\b/gi, "U$1");
    return t.replace(/\s*\|\s*/g, " | ").replace(/\s+/g, " ").trim();
  }
  function splitName(raw, M) {
    let t = clean(raw);
    if (!t) return { top: "OPPONENT", bottom: "", how: "blank name" };
    const ov = Object.keys(M.overrides || {}).find(k => fold(clean(k)) === fold(t));
    if (ov) t = clean(M.overrides[ov]);
    // singular/plural typed either way ("Maverick"/"Mavericks", "Barrie Elite"/"Elites")
    const same = (a, b) => a === b || a + "S" === b || a === b + "S";
    const clubs = (M.clubs || []).map(c => clean(c).split(" ")).sort((a, b) => b.length - a.length);
    if (t.includes("|")) {
      let [top, ...rest] = t.split("|").map(x => x.trim());
      // a typed club part still gets the list spelling, minus "Volleyball/Club/VC"
      const tw = (top || "").split(" ").map(fold);
      for (const c of clubs) {
        const fc = c.map(fold);
        if (fc.length <= tw.length && fc.every((x, i) => same(x, tw[i])) && tw.slice(fc.length).every(x => FILLER.test(x))) { top = c.join(" "); break; }
      }
      return { top: top || rest.join(" "), bottom: top ? rest.join(" ").trim() : "", how: ov ? "override" : "typed |" };
    }
    const w = t.split(" "), fw = w.map(fold);
    for (const c of clubs) {
      const fc = c.map(fold);
      if (fc.length <= fw.length && fc.every((x, i) => same(x, fw[i]))) {
        let n = fc.length;
        // "Volleyball / Volley / Club / VC…" typed right after the club is dropped
        while (n < w.length && FILLER.test(fw[n])) n++;
        // big line uses the club's spelling from the list, so it's the same every match
        return { top: c.join(" "), bottom: w.slice(n).join(" "), how: "known club" };
      }
    }
    const i = w.findIndex(x => AGE.test(x));
    if (i > 0) return { top: w.slice(0, i).join(" "), bottom: w.slice(i).join(" "), how: "unknown club · split at age group" };
    return { top: t, bottom: "", how: "unknown club · no age group" };
  }

  function widthAt(text, size, sub) {
    const m = document.getElementById(sub ? "measure2" : "measure");
    m.style.fontSize = size + "px"; m.textContent = text; return m.offsetWidth;
  }
  function largestSize(lines, hi, lo, sub, maxw) {
    const W = maxw || MAXW;
    for (let sz = hi; sz >= lo; sz -= 1) if (lines.every(l => widthAt(l, sz, sub) <= W)) return sz;
    return 0;
  }
  // Break rules for a club name too long for one line (both lines stay big):
  //   no age tag or 1–2 letter word alone · line 1 never ends on of/the/&/de/la/St…
  //   · "Club/Academy/Association" stays with the word before · biggest text, then most even.
  function layoutTop(name, o) {
    o = Object.assign({ maxw: MAXW, oneMax: ONE_MAX, oneMin: ONE_MIN, twoMax: TWO_MAX, twoMin: TWO_MIN }, o || {});
    const one = largestSize([name], o.oneMax, o.oneMin, false, o.maxw);
    if (one) return { lines: [name], size: one };
    const w = name.split(" ");
    let best = null;
    for (let i = 1; i < w.length; i++) {
      const l1 = w.slice(0, i), l2 = w.slice(i);
      if (l2.length === 1 && (GLUE.test(l2[0]) || l2[0].length <= 2)) continue;
      if (l1.length === 1 && l1[0].length <= 2) continue;
      if (JOIN.test(w[i - 1]) || ORG.test(w[i])) continue;
      const lines = [l1.join(" "), l2.join(" ")];
      const size = largestSize(lines, o.twoMax, o.twoMin, false, o.maxw);
      if (!size) continue;
      const imbalance = Math.abs(widthAt(lines[0], 50) - widthAt(lines[1], 50));
      if (!best || size > best.size || (size === best.size && imbalance < best.imbalance)) best = { lines, size, imbalance };
    }
    return best || { lines: [name], size: largestSize([name], o.oneMin, 24, false, o.maxw) || 24 };
  }

  // "RIVERSIDE RAPIDS", "THUNDERCATS POLAR": club + team words, no age group (for headlines)
  function fullName(parts) {
    return [parts.top, ...parts.bottom.split(" ").filter(x => x && !AGE.test(x))].join(" ").trim();
  }
  // team words only ("REBELS", "POLAR"), or the club when there are none
  function teamWord(parts) {
    const t = parts.bottom.split(" ").filter(x => x && !AGE.test(x)).join(" ");
    return t || parts.top;
  }
  window.VNames = { splitName, layoutTop, largestSize, widthAt, fullName, teamWord, clean, fold,
                    SUB_MAX, SUB_MIN, AGE };
})();
