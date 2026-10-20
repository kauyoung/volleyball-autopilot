// YouTube Studio upload form helper (2026-10-03) — run with the Chrome
// javascript tool on the "Details" page of the upload dialog, after replacing
// __TITLE__ and __DESC__ with JSON strings (JSON.stringify of the text).
// Fills title + description in one call and ticks "No, it's not made for kids",
// then reports what it found, so the upload needs no screenshots. If anything
// comes back false/missing, fall back to the manual steps in the skill.
// Category, playlist, thumbnail and the Visibility page stay separate steps.
(() => {
  const TITLE = __TITLE__, DESC = __DESC__;
  const out = {};
  const setText = (el, txt) => {
    el.focus();
    const r = document.createRange(); r.selectNodeContents(el);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    document.execCommand('insertText', false, txt);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const t = document.querySelector('#title-textarea #textbox');
  if (t) { setText(t, TITLE); out.title = t.innerText.trim() === TITLE.trim(); } else out.title = 'missing';
  const d = document.querySelector('#description-textarea #textbox');
  if (d) { setText(d, DESC); out.description = d.innerText.replace(/\s+/g, ' ').trim() === DESC.replace(/\s+/g, ' ').trim(); }
  else out.description = 'missing';
  const nk = document.querySelector('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]');
  if (nk) { nk.click(); out.notForKids = nk.getAttribute('aria-checked') === 'true'; } else out.notForKids = 'missing';
  return out;
})()
