"""
Home Team — upload a finished match video to YouTube through the official
YouTube Data API (2026-10-22, the owner: "Yes" to hands-off uploads).

Why: the API docs (updated 2026-10-15) say uploads from unverified API projects
are no longer forced to Private, so the video can be saved Unlisted directly —
no browser, no Ctrl+V, straight from the E: drive (resumable, any size).

One-time setup:
  1. Google Cloud project + "YouTube Data API v3" enabled + OAuth client of
     type "Desktop app"; save its JSON as _youtube-api\\client_secret.json.
     OAuth consent screen: "External", publishing status "In production"
     (in "Testing" the sign-in expires every 7 days).
  2. python yt-upload.py auth --channel main
     A browser opens; the owner signs in himself and picks the channel to upload to
     (Home Team). Claude never sees the password. -> _youtube-api\\token-main.json

Every match (after the owner's OK):
  python yt-upload.py upload --channel main --video "<...> - YouTube.mp4"
         --text "<...> - YouTube text.txt" --thumb "<...> - thumbnail.jpg"
         --playlist "Home Team 14U – 2026-2027 Season"
  -> progress + result in yt-upload-status.txt; last line "UPLOAD OK <url> unlisted"
     (only after reading the video back and confirming it is Unlisted) or
     "UPLOAD FAILED: ...".

Change an uploaded video (2026-11-22, FIXES-TODO #21 - replaces one-off scripts like _relabel-1-2.py):
  python yt-upload.py update --channel main --expect-channel "Home Team" --video-id <id or youtu.be link>
         [--text "<...> - YouTube text.txt"] [--thumb "<...> - thumbnail.jpg"]
  -> title + description from --text and/or the thumbnail; privacy is never touched (checked after:
     must still be unlisted). Last line "UPDATE OK <url> ..." or "UPDATE FAILED: ...".

Rules kept: ALWAYS Unlisted (never Public), category Sports, not made for kids,
never deletes anything on YouTube. Secrets (client_secret / tokens) stay in
_youtube-api\\ and must never go to GitHub.
"""
import argparse, json, os, random, sys, time

W = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(W, "_youtube-api")
STATUS = os.path.join(W, "yt-upload-status.txt")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]       # youtube = playlists + reading the video back
CATEGORY_SPORTS = "17"
CHUNK = 64 * 1024 * 1024


def st(msg, first=False):
    if first:                                        # 2026-11-09 (review finding 18): an old file can't pass for today's
        msg += time.strftime("  [run date %Y-%m-%d]")
    with open(STATUS, "w" if first else "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def creds(channel, interactive=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    tok = os.path.join(API_DIR, f"token-{channel}.json")
    c = Credentials.from_authorized_user_file(tok, SCOPES) if os.path.exists(tok) else None
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
    if not c or not c.valid:
        if not interactive:
            raise SystemExit(f"not signed in for channel '{channel}' — run: python yt-upload.py auth --channel {channel}")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(os.path.join(API_DIR, "client_secret.json"), SCOPES)
        c = flow.run_local_server(port=0, prompt="consent", open_browser=os.environ.get("YT_NO_BROWSER") != "1",
                                  authorization_prompt_message="SIGN-IN LINK: {url}")
    with open(tok, "w", encoding="utf-8") as f:
        f.write(c.to_json())
    return c


def service(channel, interactive=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds(channel, interactive), cache_discovery=False)


def read_text(path):
    """TITLE / DESCRIPTION file written by prep-upload.py"""
    lines = open(path, encoding="utf-8").read().replace("\r\n", "\n").split("\n")
    title, desc, mode = "", [], None
    for ln in lines:
        if ln.strip() == "TITLE":
            mode = "t"; continue
        if ln.strip() == "DESCRIPTION":
            mode = "d"; continue
        if mode == "t" and ln.strip() and not title:
            title = ln.strip()
        elif mode == "d":
            desc.append(ln)
    if not title:
        raise SystemExit("no TITLE in " + path)
    return title[:100], "\n".join(desc).strip()[:5000]


def channel_name(yt):
    r = yt.channels().list(part="snippet", mine=True).execute()
    return r["items"][0]["snippet"]["title"] if r.get("items") else "?"


def channel_matches(yt, expect):
    """2026-11-09 (review quick win 2): True when the signed-in channel is the expected one.
    expect = the channel's display name ("Home Team") or its handle ("@name"), case-insensitive."""
    r = yt.channels().list(part="snippet", mine=True).execute()
    sn = r["items"][0]["snippet"] if r.get("items") else {}
    want = expect.strip().lower()
    if want.startswith("@"):
        return (sn.get("customUrl") or "").strip().lower() == want
    return (sn.get("title") or "").strip().lower() == want


def upload(a):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    st(f"upload started: {os.path.basename(a.video)} -> channel '{a.channel}'", first=True)
    yt = service(a.channel)
    name = channel_name(yt)
    st("signed in as channel: " + name)
    if a.expect_channel and not channel_matches(yt, a.expect_channel):
        # 2026-11-09: never upload to a channel other than the one the caller named
        st(f"UPLOAD FAILED: signed in as '{name}', expected '{a.expect_channel}' - nothing was uploaded")
        return 1
    title, desc = read_text(a.text)
    body = {"snippet": {"title": title, "description": desc, "categoryId": CATEGORY_SPORTS},
            "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False, "embeddable": True}}
    media = MediaFileUpload(a.video, chunksize=CHUNK, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=False)
    resp, tries, last = None, 0, -10
    size = os.path.getsize(a.video)
    t0 = time.time()
    while resp is None:
        try:
            prog, resp = req.next_chunk()
            tries = 0
            if prog:
                pct = int(prog.progress() * 100)
                if pct >= last + 10:
                    mb_s = prog.resumable_progress / 1e6 / max(1, time.time() - t0)
                    st(f"uploading {pct}% of {size / 1e9:.1f} GB ({mb_s:.1f} MB/s)"); last = pct
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and tries < 8:
                tries += 1; time.sleep(min(60, 2 ** tries + random.random())); continue
            raise
        except (ConnectionError, TimeoutError, OSError):
            if tries < 8:
                tries += 1; time.sleep(min(60, 2 ** tries + random.random())); continue
            raise
    vid = resp["id"]
    st(f"uploaded: https://youtu.be/{vid} ({(time.time() - t0) / 60:.1f} min)")
    if a.thumb and os.path.exists(a.thumb):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(a.thumb, mimetype="image/jpeg")).execute()
            st("thumbnail set")
        except HttpError as e:
            st(f"thumbnail NOT set ({e.resp.status}) — set it in Studio")
    pl_note = ""
    if a.playlist_id:                                # 2026-11-09 (review finding 17): by id - a renamed playlist can't be missed
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": a.playlist_id,
                                      "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            st(f"added to playlist {a.playlist_id}" + (f" ('{a.playlist}')" if a.playlist else ""))
        except HttpError as e:
            st(f"playlist {a.playlist_id} NOT set ({e.resp.status}) - add it in Studio")
            pl_note = " - playlist NOT set"
    elif a.playlist:
        pl = None
        r = {"nextPageToken": None}
        while pl is None and "nextPageToken" in r:
            r = yt.playlists().list(part="snippet", mine=True, maxResults=50,
                                    pageToken=r.get("nextPageToken")).execute()
            pl = next((p["id"] for p in r.get("items", []) if p["snippet"]["title"].strip() == a.playlist.strip()), None)
            if not r.get("nextPageToken"):
                break
        if pl:
            yt.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pl,
                                      "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            st(f"added to playlist '{a.playlist}'")
        else:
            st(f"playlist '{a.playlist}' NOT found — add it in Studio")
            pl_note = " - playlist NOT set"
    v = yt.videos().list(part="status,snippet", id=vid).execute()["items"][0]
    priv = v["status"]["privacyStatus"]
    if priv != "unlisted":
        st(f"UPLOAD FAILED: video is '{priv}', not unlisted — https://youtu.be/{vid} (fix it in Studio)")
        return 2
    st(f"UPLOAD OK https://youtu.be/{vid} unlisted{pl_note} — '{v['snippet']['title']}'")   # 2026-11-09: a missed playlist shows here too
    return 0


def update(a):
    """2026-11-22 (#21): change title/description and/or thumbnail of an uploaded video. Never privacy, never delete."""
    import re as _re
    from googleapiclient.http import MediaFileUpload
    vid = _re.sub(r"^.*(?:youtu\.be/|v=)", "", a.video_id.strip()).split("&")[0].split("?")[0]
    st(f"update started: {vid} -> channel '{a.channel}'", first=True)
    if not a.text and not a.thumb:
        st("UPDATE FAILED: give --text and/or --thumb"); return 1
    yt = service(a.channel)
    name = channel_name(yt)
    st("signed in as channel: " + name)
    if a.expect_channel and not channel_matches(yt, a.expect_channel):
        st(f"UPDATE FAILED: signed in as '{name}', expected '{a.expect_channel}' - nothing was changed")
        return 1
    items = yt.videos().list(part="snippet,status", id=vid).execute().get("items") or []
    if not items:
        st(f"UPDATE FAILED: video {vid} not found on '{name}'"); return 1
    done = []
    if a.text:
        title, desc = read_text(a.text)
        sn = items[0]["snippet"]
        sn["title"], sn["description"] = title, desc
        yt.videos().update(part="snippet", body={"id": vid, "snippet": {k: sn[k] for k in
                           ("title", "description", "categoryId", "tags", "defaultLanguage") if k in sn}}).execute()
        done.append("title + description")
    if a.thumb:
        if not os.path.exists(a.thumb):
            st("UPDATE FAILED: thumbnail file not found: " + a.thumb); return 1
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(a.thumb, mimetype="image/jpeg")).execute()
        done.append("thumbnail")
    v = yt.videos().list(part="snippet,status", id=vid).execute()["items"][0]
    priv = v["status"]["privacyStatus"]
    st(f"UPDATE OK https://youtu.be/{vid} {priv} - changed: {', '.join(done)} - '{v['snippet']['title']}'"
       + ("" if priv == "unlisted" else f" - NOTE: the video is {priv}, not unlisted (not changed here)"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("auth"); s.add_argument("--channel", required=True)
    s = sub.add_parser("whoami"); s.add_argument("--channel", required=True)
    s = sub.add_parser("upload")
    for k in ("channel", "video", "text"):
        s.add_argument("--" + k, required=True)
    s.add_argument("--thumb"); s.add_argument("--playlist")
    s.add_argument("--expect-channel")
    s.add_argument("--playlist-id")                  # 2026-11-09: preferred over --playlist (title)
    s = sub.add_parser("update")                     # 2026-11-22 (#21)
    s.add_argument("--channel", required=True); s.add_argument("--video-id", required=True)
    s.add_argument("--text"); s.add_argument("--thumb"); s.add_argument("--expect-channel")
    a = ap.parse_args()
    os.makedirs(API_DIR, exist_ok=True)
    if a.cmd == "auth":
        print("signed in as channel:", channel_name(service(a.channel, interactive=True)))
        return 0
    if a.cmd == "whoami":
        print("signed in as channel:", channel_name(service(a.channel)))
        return 0
    try:
        return update(a) if a.cmd == "update" else upload(a)
    except SystemExit:
        raise
    except Exception as e:
        st(f"UPLOAD FAILED: {e!r:.300}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
