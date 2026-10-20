// YouTube Studio small checks (2026-10-08, "video" mode added 2026-10-14) — use instead of
// get_page_text, which dumps the whole page. Replace __MODE__ with "channel", "verify",
// "finish" or "video", and __TITLE__ with a JSON string (verify/video; null otherwise).
//   channel: which channel Studio is on -> {name, id, url}
//   verify : on the Content page, the newest rows -> [{title, visibility}] (+ match flag)
//   finish : the result youtube-finish.js left in window.__ytFinish -> its object, or
//            {running:true, seconds} while it's still busy, or {none:true} if it never ran here
//   video  : on the video's own Studio page (studio.youtube.com/video/<id>/edit) ->
//            {title, visibility, playlists, ok} ; ok = title matches AND Visibility is Unlisted
(() => {
  const MODE = __MODE__, TITLE = __TITLE__;
  const t = x => (x || '').replace(/\s+/g, ' ').trim();
  if (MODE === 'channel') {
    let id = null;
    try { id = window.ytcfg && (ytcfg.get('CHANNEL_ID') || ytcfg.data_?.CHANNEL_ID); } catch (e) {}
    const m = location.pathname.match(/channel\/(UC[\w-]+)/);
    const name = t(document.querySelector('#entity-name, ytcp-navigation-drawer #entity-name, .entity-name')?.innerText);
    return { name: name || null, id: id || (m && m[1]) || null, url: location.href.slice(0, 120) };
  }
  if (MODE === 'finish') {
    const r = window.__ytFinish;
    if (!r) return { none: true };
    return r.running ? { running: true, seconds: Math.round((Date.now() - r.started) / 1000) } : r;
  }
  if (MODE === 'video') {
    const title = t(document.querySelector('#title-textarea #textbox')?.innerText);
    const visTxt = t(document.querySelector('ytcp-video-metadata-visibility, ytcp-video-visibility-select, #visibility-text')?.innerText).replace(/^Visibility\s*/i, '');
    const playlists = t(document.querySelector('ytcp-video-metadata-playlists')?.innerText).replace(/^Playlists?\s*/i, '');
    const ok = !!title && (!TITLE || title === t(TITLE)) && /^unlisted/i.test(visTxt);
    return { title: title.slice(0, 100), visibility: visTxt.slice(0, 40), playlists: playlists.slice(0, 100), ok };
  }
  const rows = [...document.querySelectorAll('ytcp-video-row')].slice(0, 3).map(r => ({
    title: t(r.querySelector('#video-title')?.innerText).slice(0, 100),
    visibility: t(r.querySelector('.visibility-cell, #visibility-text, .tablecell-visibility')?.innerText).slice(0, 40)
  }));
  const hit = TITLE ? rows.find(r => r.title === t(TITLE).slice(0, 100)) : null;
  return { rows, match: hit ? /unlisted/i.test(hit.visibility) : false };
})()
