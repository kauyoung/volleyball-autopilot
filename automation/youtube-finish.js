// YouTube Studio upload — everything after title/description in ONE call (rewritten 2026-10-14).
// Run with the Chrome javascript tool on the upload dialog's Details page, after
// youtube-fill.js and the thumbnail. Replace before running:
//   __PLAYLIST__ = JSON string of the playlist name, or null (no playlist)
//   __SAVE__     = true to save at the end (only if every check passed), else false
//   __DRY__      = true to only report which controls it can find (no clicks)
// Does: Show more -> Category "Sports" -> playlist (ticked, Done) -> Next x3 (each click
// CONFIRMED by the stepper: Details -> Video elements -> Checks -> Visibility; retried up to
// 3 times, else reports stuck:"<step>") -> Unlisted -> Save. STANDING RULE: always Unlisted,
// saved right away, every upload; if "still checking" prompts, click "Publish anyway" (still
// Unlisted). Never Public. saved:true ONLY when the upload dialog closed or a
// published/processing dialog appeared. Returns one small object; any false/"missing" = do
// that step by hand (see WORKFLOW-NOTES).
// Result (2026-10-14): the javascript tool often returns {} for this long script, so the result
// is ALSO left on the page in window.__ytFinish ({running:true} while busy). Read it with
// youtube-check.js mode "finish" (poll until running is gone). Never run this script twice.
(async () => {
  const PLAYLIST = __PLAYLIST__, SAVE = __SAVE__, DRY = __DRY__;
  const out = {};
  window.__ytFinish = { running: true, started: Date.now() };
  try {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, ms = 6000) => { for (let t = 0; t < ms; t += 250) { const v = fn(); if (v) return v; await sleep(250); } return null; };
  const norm = x => (x || '').replace(/[‐-―]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
  const vis = e => e && e.offsetParent !== null;
  const byText = (sel, re, root = document) => [...root.querySelectorAll(sel)].find(e => vis(e) && re.test((e.innerText || '').trim()));
  const q = s => document.querySelector(s);
  const STEPS = ['Details', 'Video elements', 'Checks', 'Visibility'];
  // current step index from the stepper (aria-selected on #step-badge-N)
  const cur = () => { for (let i = 0; i < 4; i++) { const b = q('#step-badge-' + i); if (b && b.getAttribute('aria-selected') === 'true') return i; } return -1; };
  const dialogOpen = () => vis(q('ytcp-uploads-dialog'));

  // 1. Show more
  const more = q('ytcp-uploads-dialog #toggle-button') || byText('ytcp-button, button', /^Show more$/i);
  out.showMore = !!more;
  if (DRY) {
    out.category = !!q('ytcp-uploads-dialog #category, ytcp-form-select#category');
    out.playlistDropdown = !!q('ytcp-video-metadata-playlists ytcp-dropdown-trigger, ytcp-video-metadata-playlists');
    out.next = !!q('#next-button'); out.stepper = cur(); out.unlisted = !!q('tp-yt-paper-radio-button[name="UNLISTED"]');
    window.__ytFinish = out;
    return out;
  }
  if (more && /more/i.test(more.innerText)) { more.click(); await sleep(800); }

  // 2. Category: Sports
  try {
    const cat = await waitFor(() => q('ytcp-uploads-dialog #category, ytcp-form-select#category'));
    if (!cat) out.category = 'missing';
    else if (/sport/i.test(cat.innerText)) out.category = true;
    else {
      (cat.querySelector('ytcp-dropdown-trigger') || cat).click();
      const item = await waitFor(() => byText('tp-yt-paper-item, ytcp-text-menu tp-yt-paper-item, [role="option"]', /^Sports?$/i));
      if (item) { item.click(); await sleep(600); }
      out.category = /sport/i.test(cat.innerText);
    }
  } catch (e) { out.category = 'error ' + e.message; }

  // 3. Playlist
  if (PLAYLIST) {
    try {
      const trig = q('ytcp-video-metadata-playlists ytcp-dropdown-trigger') || q('ytcp-video-metadata-playlists');
      if (!trig) out.playlist = 'missing';
      else {
        trig.click();
        const dlg = await waitFor(() => { const d = q('ytcp-playlist-dialog'); return vis(d) ? d : null; });
        const want = norm(PLAYLIST);
        const label = dlg && await waitFor(() => [...dlg.querySelectorAll('#checkbox-label, .checkbox-label, span, label')]
          .find(e => norm(e.innerText) === want));
        if (!label) out.playlist = 'not found';
        else {
          const box = label.closest('ytcp-ve, li, #checkbox-container, ytcp-checkbox-group')?.querySelector('ytcp-checkbox-lit, [role="checkbox"]') || label;
          const checked = () => (box.getAttribute('aria-checked') || box.querySelector('[aria-checked]')?.getAttribute('aria-checked')) === 'true';
          if (!checked()) { box.click(); await sleep(500); }
          out.playlist = checked();
          const done = dlg.querySelector('.done-button, #done-button') || byText('ytcp-button, button', /^Done$/i, dlg);
          if (done) { done.click(); await sleep(800); }
        }
      }
    } catch (e) { out.playlist = 'error ' + e.message; }
  } else out.playlist = 'none';

  // 4. Next x3 -> Visibility, each click confirmed by the stepper; retry up to 3x per step
  let step = cur(); out.startStep = STEPS[step] || step;
  while (step >= 0 && step < 3) {
    let advanced = false;
    for (let attempt = 0; attempt < 3 && !advanced; attempt++) {
      const nx = q('#next-button');
      if (nx && !nx.hasAttribute('disabled')) nx.click();
      advanced = !!(await waitFor(() => cur() > step, 5000));
      if (!advanced) await sleep(1000);
    }
    if (!advanced) { out.stuck = STEPS[step] || 'unknown'; break; }
    step = cur();
  }
  if (step < 0) out.stuck = out.stuck || 'stepper not found';
  out.step = STEPS[cur()] || cur();

  // 5. Unlisted (only on the Visibility step)
  if (!out.stuck && cur() === 3) {
    const un = await waitFor(() => q('tp-yt-paper-radio-button[name="UNLISTED"]'));
    if (!un) out.unlisted = 'missing';
    else { un.click(); await sleep(500); out.unlisted = un.getAttribute('aria-checked') === 'true'; }
  } else out.unlisted = false;
  const pub = q('tp-yt-paper-radio-button[name="PUBLIC"]');
  out.publicOff = !pub || pub.getAttribute('aria-checked') !== 'true';

  // 6. Save — only when everything passed; saved:true only if the dialog really closed
  const okAll = !out.stuck && out.category === true && (out.playlist === true || out.playlist === 'none') && out.unlisted === true && out.publicOff;
  if (SAVE && okAll) {
    const sv = q('#done-button');
    if (!sv || sv.hasAttribute('disabled')) out.saved = 'save button not ready';
    else {
      sv.click();
      const finished = () => !dialogOpen() || vis(q('ytcp-video-share-dialog, ytcp-uploads-still-processing-dialog'))
        || /video (published|saved)/i.test(document.body.innerText.slice(0, 20000));
      let tries = 0;
      while (tries++ < 12 && !finished()) {
        // "still checking" prompt -> Publish anyway (video is already Unlisted, confirmed above)
        const pa = byText('ytcp-button, button, tp-yt-paper-button', /^(Publish anyway|Save anyway)$/i);
        const unNow = q('tp-yt-paper-radio-button[name="UNLISTED"]');
        if (pa && (!unNow || unNow.getAttribute('aria-checked') === 'true')) { pa.click(); out.publishAnyway = true; }
        await sleep(1500);
      }
      out.saved = !!finished();
      if (!out.saved) out.saved = false, out.note = 'dialog still open after Save';
    }
  } else out.saved = SAVE ? 'skipped (a check failed)' : false;
  } catch (e) { out.error = String(e && e.message || e).slice(0, 200); }
  window.__ytFinish = out;
  return out;
})()
