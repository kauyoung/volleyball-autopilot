/**
 * Volleyball Autopilot scorekeeper → Google Drive receiver
 *
 * Deployed once as a Google Apps Script "Web app" in the owner's Google account.
 * When a match ends, the scorekeeper app POSTs the match file here, and this
 * saves it into the Drive folder below.
 *
 * What it can do: create .json files in ONE folder (and its "_held" subfolder).
 * Nothing else — it never reads, lists or deletes anything else in Drive.
 *
 * Deploy: Deploy → New deployment → type "Web app" →
 *         Execute as: Me   ·   Who has access: Anyone
 * Update: paste this file over the old one → Deploy → Manage deployments →
 *         edit (pencil) → Version: New version → Deploy (the web-app URL stays the same).
 *
 * 2026-11-04 hardening (the key is readable in the public page, so the script itself
 * makes sure nothing it receives can do harm):
 *  - Only real match files are accepted (name pattern, size, structure, dates).
 *  - A file that already exists is never replaced by a DIFFERENT one: the newcomer
 *    goes to the "_held" subfolder (the video workflow only reads the main folder).
 *  - At most MAX_PER_DAY files a day.
 */

const FOLDER_NAME = 'Venom Matches – Scorekeeper';
const HELD_NAME   = '_held';
const SECRET_KEY  = 'CHANGE-ME';    // must match DRIVE_KEY in the scorekeeper page
const MAX_PER_DAY = 20;
const MAX_BYTES   = 300000;         // a long 3-set match is ~40 KB
const MAX_EVENTS  = 800;

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
    if (!e || !e.postData || !e.postData.contents) return reply({ ok: false, error: 'empty' });
    if (e.postData.contents.length > MAX_BYTES) return reply({ ok: false, error: 'too big' });
    const body = JSON.parse(e.postData.contents);
    if (SECRET_KEY === 'CHANGE-ME' || body.key !== SECRET_KEY) return reply({ ok: false, error: 'bad key' });

    const name = String(body.filename || '');
    const match = body.match;
    const problem = checkMatch(name, match);
    if (problem) return reply({ ok: false, error: 'not a match file: ' + problem });

    const content = JSON.stringify(match, null, 1);
    const folder = getFolder(FOLDER_NAME, null);
    const existing = folder.getFilesByName(name);
    if (existing.hasNext()) {
      const old = existing.next();
      if (old.getBlob().getDataAsString() === content) {
        return reply({ ok: true, name: name, folder: FOLDER_NAME, same: true });   // re-send of the same match
      }
      if (!countToday()) return reply({ ok: false, error: 'daily limit' });
      const stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd-HHmmss');
      const heldName = name.replace(/\.json$/, '') + ' (held ' + stamp + ').json';
      getFolder(HELD_NAME, folder).createFile(heldName, content, 'application/json');
      return reply({ ok: true, name: heldName, folder: FOLDER_NAME + '/' + HELD_NAME, held: true });
    }
    if (!countToday()) return reply({ ok: false, error: 'daily limit' });
    folder.createFile(name, content, 'application/json');
    return reply({ ok: true, name: name, folder: FOLDER_NAME });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    try { lock.releaseLock(); } catch (x) {}
  }
}

// Returns null if this looks like a real scorekeeper match file, else a short reason.
function checkMatch(name, m) {
  const fm = /^(\d{4}-\d{2}-\d{2})-\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*-vs-[a-z0-9]+(?:-[a-z0-9]+)*\.json$/.exec(name);
  if (!fm || name.length > 120) return 'file name';
  if (!m || typeof m !== 'object' || m.version !== 1) return 'version';
  if (m.date !== fm[1]) return 'date';
  if (!isName(m.team1) || !isName(m.team2)) return 'team names';
  if (!Array.isArray(m.events) || m.events.length < 1 || m.events.length > MAX_EVENTS) return 'events';
  for (const ev of m.events) {
    if (!ev || typeof ev !== 'object') return 'event';
    if (!isNum(ev.t, 0, 6 * 3600) || !isInt(ev.set, 1, 9) || !isInt(ev.score1, 0, 99) || !isInt(ev.score2, 0, 99) ||
        !isInt(ev.sets1, 0, 9) || !isInt(ev.sets2, 0, 9) || !isInt(ev.serve, 0, 2)) return 'event values';
  }
  if (m.timeouts !== undefined && (!Array.isArray(m.timeouts) || m.timeouts.length > 60)) return 'timeouts';
  const started = Date.parse(m.startedAt);
  if (!isFinite(started)) return 'start time';
  const now = Date.now();
  if (started > now + 24 * 3600e3 || started < now - 30 * 24 * 3600e3) return 'start time';
  return null;
}
function isName(s) { return typeof s === 'string' && s.length >= 1 && s.length <= 40; }
function isNum(x, lo, hi) { return typeof x === 'number' && isFinite(x) && x >= lo && x <= hi; }
function isInt(x, lo, hi) { return isNum(x, lo, hi) && Math.floor(x) === x; }

// Counts a new file against today's limit; false when the limit is reached.
function countToday() {
  const props = PropertiesService.getScriptProperties();
  const key = 'count-' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  const n = Number(props.getProperty(key) || 0);
  if (n >= MAX_PER_DAY) return false;
  props.setProperty(key, String(n + 1));
  return true;
}

// Visiting the URL in a browser just confirms it's alive.
function doGet() {
  return reply({ ok: true, service: 'volleyball-autopilot-drive', folder: FOLDER_NAME });
}

function getFolder(name, parent) {
  const found = parent ? parent.getFoldersByName(name) : DriveApp.getFoldersByName(name);
  if (found.hasNext()) return found.next();
  return parent ? parent.createFolder(name) : DriveApp.createFolder(name);
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
