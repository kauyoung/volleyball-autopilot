"""
Stop alerts (2026-11-22, FIXES-TODO #1). A stop must never be silent, even if Claude misses it.

alert(title, message) does three things, each on its own (one failing never blocks the others):
  1. PC sound   - 5 loud beeps + the Windows "critical stop" sound
  2. PC pop-up  - a Windows notification (toast) with the message
  3. phone push - ntfy.sh (free ntfy app on the owner's phone, subscribed to the topic in alert-config.json)
Every alert is also appended to alerts-log.txt. The same message is not repeated within 30 min.

Called by run-match.py / run-tournament.py on any STOPPED line, and by resolve-watch.py when Resolve
goes GONE or FROZEN while a run is active. A run-match started by run-tournament (env VB_ALERT_PARENT=1)
leaves the alert to the tournament so the owner gets one alert, not two.
Test from a shell:  python alert.py test
"""
import json, os, subprocess, sys, threading, time, urllib.request

W = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(W, "alert-config.json")
LOG = os.path.join(W, "alerts-log.txt")
LAST = os.path.join(W, "alerts-last.json")
REPEAT_S = 30 * 60
NOWIN = 0x08000000


def _cfg():
    try:
        return json.load(open(CFG, encoding="utf-8"))
    except Exception:
        return {}


def _log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _seen_recently(key):
    try:
        last = json.load(open(LAST, encoding="utf-8"))
    except Exception:
        last = {}
    now = time.time()
    last = {k: t for k, t in last.items() if now - t < REPEAT_S}
    hit = key in last
    if not hit:
        last[key] = now
    try:
        json.dump(last, open(LAST, "w", encoding="utf-8"))
    except Exception:
        pass
    return hit


def _sound():
    try:
        import winsound
        for _ in range(5):
            winsound.Beep(1400, 350)
            time.sleep(0.15)
        winsound.PlaySound("SystemHand", winsound.SND_ALIAS)
    except Exception as e:
        _log(f"  sound failed: {e!r}")


PS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:VB_T)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:VB_M)) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($t)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)
"""


def _popup(title, msg):
    try:
        env = dict(os.environ, VB_T=title[:120], VB_M=msg[:400])
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_TOAST],
                           env=env, capture_output=True, text=True, timeout=30, creationflags=NOWIN)
        if r.returncode or r.stderr.strip():
            _log("  pop-up failed: " + (r.stderr.strip() or f"exit {r.returncode}")[:300])
    except Exception as e:
        _log(f"  pop-up failed: {e!r}")


def _push(title, msg, topic):
    try:
        req = urllib.request.Request("https://ntfy.sh/" + topic, data=msg.encode("utf-8"), method="POST",
                                     headers={"Title": title.encode("ascii", "replace").decode(),
                                              "Priority": "urgent", "Tags": "rotating_light"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        _log(f"  phone push failed: {e!r}")


def alert(title, msg, key=None, wait=True):
    """never raises. wait=True: return after all three are done (max ~40 s) so a sys.exit right after
    doesn't cut them off."""
    try:
        if os.environ.get("VB_ALERT_PARENT") == "1" and not os.environ.get("VB_ALERT_FORCE"):
            return
        if _seen_recently(key or (title + "|" + msg)):
            return
        c = _cfg()
        _log(f"ALERT {title}: {msg}")
        jobs = []
        if c.get("pc_sound", True):
            jobs.append(threading.Thread(target=_sound, daemon=True))
        if c.get("pc_popup", True):
            jobs.append(threading.Thread(target=_popup, args=(title, msg), daemon=True))
        if c.get("phone_push", True) and c.get("ntfy_topic"):
            jobs.append(threading.Thread(target=_push, args=(title, msg, c["ntfy_topic"]), daemon=True))
        for j in jobs:
            j.start()
        if wait:
            for j in jobs:
                j.join(40)
    except Exception as e:
        _log(f"  alert failed: {e!r}")


def resolve_cause(text=""):
    """2026-11-22 (#6): name the cause of a stop - "Resolve crashed at HH:MM" instead of "finish crashed"."""
    try:
        last = open(os.path.join(W, "resolve-watch.txt"), encoding="utf-8").read().strip().splitlines()[-1]
        fresh = time.time() - os.path.getmtime(os.path.join(W, "resolve-watch.txt")) < 120
    except Exception:
        last, fresh = "", False
    if fresh and "GONE" in last:
        return f"Resolve crashed or was closed (gone since {last[11:16]})"
    if fresh and "FROZEN" in last:
        return "Resolve is frozen (" + last[20:] + ")"
    if "'NoneType' object is not callable" in (text or "") or "'NoneType' object has no attribute" in (text or ""):
        return "Resolve stopped answering at " + time.strftime("%H:%M") + " (most likely it crashed)"
    return ""


def run_active(max_idle_s=20 * 60):
    """True while run-match or run-tournament is mid-run (status written recently, last line not final)."""
    final = ("STOPPED", "RUN DONE", "EXPORTS DONE", "DRY RUN DONE")
    for f in ("tournament-status.txt", "run-match-status.txt"):
        p = os.path.join(W, f)
        try:
            if time.time() - os.path.getmtime(p) > max_idle_s:
                continue
            lines = open(p, encoding="utf-8").read().strip().splitlines()
            if lines and not any(k in lines[-1] for k in final):
                return True
        except Exception:
            pass
    return False


if __name__ == "__main__":
    if sys.argv[1:2] == ["test"]:
        os.environ["VB_ALERT_FORCE"] = "1"
        alert("Volleyball Autopilot test", "Test alert " + time.strftime("%H:%M:%S") + " - if you see this, alerts work.",
              key="test " + str(time.time()))
        print(open(LOG, encoding="utf-8").read().strip().splitlines()[-3:])
