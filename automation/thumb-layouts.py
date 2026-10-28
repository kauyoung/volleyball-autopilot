"""
Volleyball Autopilot - thumbnail layout PROPOSALS (2026-10-06, Kenny: "the placement of the texts
and the logo doesn't look right ... keep all the texts, just move them around").
Not used by the workflow yet - make-thumbnail.py stays the live one until Kenny picks.
  python thumb-layouts.py <A|B> <match.json> <frame.jpg> <out.jpg> <fonts dir>
A = "centred matchup": everything on the centre line, badge on top, event box at the bottom
B = "hero badge": a large badge on the right, the text block left-aligned beside it
Same safe area as the live one: 120 px left/right, >= 84 px top/bottom.
"""
import json, os, sys, datetime
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
W, H = 1280, 720
GREEN=(112,213,73); WHITE=(255,255,255); INK=(2,3,3); GREY=(150,150,150)
FILES=r"C:\Users\YOURNAME\scoreboard-pipeline"
LOGO1=FILES+r"\team-logo-square.png"
MX, TOP, BOTTOM = 120, 84, H-88


def fit_name(d, text, font, maxw, big, small, mn):
    for s in range(big, small-1, -4):
        if d.textlength(text, font=font(s)) <= maxw: return [text], s
    words = text.split()
    if len(words) > 1:
        for s in range(small, mn-1, -4):
            best = None
            for i in range(1, len(words)):
                a, b = " ".join(words[:i]), " ".join(words[i:])
                w = max(d.textlength(a, font=font(s)), d.textlength(b, font=font(s)))
                if w <= maxw and (best is None or w < best[0]): best = (w, [a, b])
            if best: return best[1], s
    lines = [text] if len(words) == 1 else [" ".join(words[:len(words)//2]), " ".join(words[len(words)//2:])]
    out = []
    for ln in lines:
        while d.textlength(ln, font=font(mn)) > maxw and len(ln) > 1: ln = ln[:-2].rstrip() + "\u2026"
        out.append(ln)
    return out, mn


def badge(img, cx, cy, r):
    d = ImageDraw.Draw(img)
    d.ellipse([cx-r-6, cy-r-6, cx+r+6, cy+r+6], fill=GREEN)
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=INK)
    sz = 2*r; lg = Image.open(LOGO1).convert("RGB").resize((sz, sz), Image.LANCZOS)
    mk = Image.new("L", (sz, sz)); ImageDraw.Draw(mk).ellipse([0, 0, sz-1, sz-1], fill=255)
    img.paste(lg, (cx-r, cy-r), mk)


def background(frame, mode):
    bg = Image.open(frame).convert("RGB"); bw, bh = bg.size
    ch = int(bh*0.80); cw = int(ch*16/9); x0 = max(0, (bw-cw)//2)
    bg = bg.crop((x0, 0, x0+cw, ch)).resize((W, H), Image.LANCZOS)
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    sh = Image.new("L", (W, H)); sd = ImageDraw.Draw(sh)
    if mode == "A":      # even dark wash, a little darker at the edges (vignette) so the centre reads
        bg = ImageEnhance.Brightness(bg).enhance(0.75)
        v = Image.new("L", (W, H), 0); ImageDraw.Draw(v).ellipse([-260, -220, W+260, H+220], fill=255)
        v = v.filter(ImageFilter.GaussianBlur(160))
        bg = Image.composite(bg, Image.new("RGB", (W, H), INK), v)
    else:                # dark from the left for the text, light on the right behind the badge
        for x in range(W): sd.line([(x, 0), (x, H)], fill=int(235*max(0, 1-x/(W*0.78))))
        bg = Image.composite(Image.new("RGB", (W, H), INK), bg, sh)
    return bg


def main(layout, match, frame, out, fdir):
    m = json.load(open(match, encoding="utf-8"))
    t1 = (m.get("team1") or "Home Team").upper(); t2 = (m.get("team2") or "Opponent").upper()
    try: date = datetime.date.fromisoformat(m["date"]).strftime("%b %d, %Y").upper()
    except Exception: date = ""
    try: event = open(os.path.join(os.path.dirname(os.path.abspath(match)), "event.txt"), encoding="utf-8").read().strip().upper()
    except Exception: event = ""
    tile = event or ("SCRIMMAGE" if (m.get("format") or {}).get("mode") == "open" else "")
    NB = os.path.join(fdir, "Gotham Narrow Bold.otf"); MED = os.path.join(fdir, "Gotham Medium.otf")
    nb = lambda s: ImageFont.truetype(NB, s); md = lambda s: ImageFont.truetype(MED, s)
    img = background(frame, layout); d = ImageDraw.Draw(img)

    def pill(x, y, anchor_centre=False):
        """MATCH REPLAY pill + date; returns total width"""
        pw = 250; dw = d.textlength(date, font=md(26)); tw = pw + 22 + dw
        x0 = x - tw/2 if anchor_centre else x
        d.rounded_rectangle([x0, y, x0+pw, y+46], radius=23, fill=GREEN)
        d.text((x0+pw/2, y+24), "MATCH REPLAY", font=nb(26), fill=INK, anchor="mm")
        d.text((x0+pw+22, y+24), date, font=md(26), fill=(225, 225, 225), anchor="lm")

    def event_tile(x, y, maxw, centre=False):
        if not tile: return 0
        t = tile
        for ts in range(34, 21, -2):
            if d.textlength(t, font=nb(ts)) <= maxw-64: break
        while d.textlength(t, font=nb(ts)) > maxw-64 and len(t) > 1: t = t[:-2].rstrip()+"\u2026"
        w = d.textlength(t, font=nb(ts)) + 64; x0 = x - w/2 if centre else x
        d.rounded_rectangle([x0, y, x0+w, y+70], radius=18, fill=(24, 26, 26), outline=GREEN, width=3)
        d.text((x0+32, y+36), t, font=nb(ts), fill=(245, 245, 245), anchor="lm")
        return 70

    if layout == "A":
        cx = W // 2; maxw = W - 2*MX
        for scale in [1.0, 0.94, 0.88, 0.82, 0.76, 0.7]:
            r = int(54*scale)
            l1, s1 = fit_name(d, t1, nb, maxw, int(104*scale), int(80*scale), 48)
            l2, s2 = fit_name(d, t2, nb, maxw, int(84*scale), int(66*scale), 44)
            hb = 2*r+12; hp = 46; hv = 40; ht = 70 if tile else 0
            h1 = int(len(l1)*s1*1.02); h2 = int(len(l2)*s2*1.02)
            gaps = [22, 34, 16, 16, 34 if tile else 0]
            total = hb + hp + h1 + hv + h2 + ht + sum(gaps)
            if total <= BOTTOM - TOP: break
        y = TOP + max(0, (BOTTOM - TOP - total) // 2)
        badge(img, cx, y + r + 6, r); y += hb + gaps[0]
        pill(cx, y, anchor_centre=True); y += hp + gaps[1]
        for ln in l1:
            y += int(s1*1.02); d.text((cx, y - int(s1*0.2)), ln, font=nb(s1), fill=GREEN, anchor="ms")
        y += gaps[2]
        vy = y + hv//2; vf = nb(34); vw = d.textlength("VS", font=vf)
        d.text((cx, vy), "VS", font=vf, fill=WHITE, anchor="mm")
        d.line([(cx-230, vy), (cx-vw/2-22, vy)], fill=GREY, width=3); d.line([(cx+vw/2+22, vy), (cx+230, vy)], fill=GREY, width=3)
        y += hv + gaps[3]
        for ln in l2:
            y += int(s2*1.02); d.text((cx, y - int(s2*0.2)), ln, font=nb(s2), fill=WHITE, anchor="ms")
        y += gaps[4]
        event_tile(cx, y, maxw, centre=True)
    else:
        R = 132; bcx = W - MX - R - 6; bcy = H // 2
        glow = Image.new("L", (W, H), 0); ImageDraw.Draw(glow).ellipse([bcx-R-90, bcy-R-90, bcx+R+90, bcy+R+90], fill=150)
        img = Image.composite(Image.new("RGB", (W, H), INK), img, glow.filter(ImageFilter.GaussianBlur(60))); d = ImageDraw.Draw(img)
        badge(img, bcx, bcy, R)
        L = MX; maxw = bcx - R - 6 - 56 - L
        pill(L, TOP)
        for scale in [1.0, 0.94, 0.88, 0.82, 0.76, 0.7]:
            l1, s1 = fit_name(d, t1, nb, maxw, int(100*scale), int(78*scale), 46)
            l2, s2 = fit_name(d, t2, nb, maxw, int(80*scale), int(64*scale), 42)
            h1 = int(len(l1)*s1*1.02); h2 = int(len(l2)*s2*1.02)
            blk = h1 + 16 + 40 + 16 + h2
            if blk <= (BOTTOM - (70 + 30 if tile else 0)) - (TOP + 46 + 40): break
        top = TOP + 46 + 40; bot = BOTTOM - (70 + 30 if tile else 0)
        y = top + max(0, (bot - top - blk) // 2)
        for ln in l1:
            y += int(s1*1.02); d.text((L, y - int(s1*0.2)), ln, font=nb(s1), fill=GREEN, anchor="ls")
        y += 16; vy = y + 20; vf = nb(34)
        d.text((L, vy), "VS", font=vf, fill=WHITE, anchor="lm")
        vw = d.textlength("VS", font=vf); d.line([(L+vw+20, vy), (L+maxw*0.62, vy)], fill=GREY, width=3)
        y += 40 + 16
        for ln in l2:
            y += int(s2*1.02); d.text((L, y - int(s2*0.2)), ln, font=nb(s2), fill=WHITE, anchor="ls")
        event_tile(L, BOTTOM - 70, maxw)
    img.save(out, quality=92)
    print("saved", out)


if __name__ == "__main__":
    main(*sys.argv[1:6])
