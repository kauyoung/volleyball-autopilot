# Volleyball Autopilot YouTube thumbnail (layout approved by Kenny 2026-10-05/06).
#   PY make-thumbnail.py <match.json> <frame.jpg> <out.jpg> [fonts-dir]
# One left edge; "VS" centred between the names with a rule each side; our badge only;
# one tile (event name, else SCRIMMAGE, else none). Safe margins: 120 px left/right, >= 84 px
# top/bottom for the text (WhatsApp / YouTube crop and round the corners); the corner badge sits
# 54 px from the top so a long opponent's VS rule never touches it (Kenny 2026-10-06; he went
# back to this layout from the "hero badge" option B, kept in _backup-2026-10-06-before-final-tidy).
# Long names: shrink -> two lines -> smaller -> trim with "…" (never past the margins).
# The whole block is re-flowed so nothing ever overlaps the tile or the bottom margin.
# Old layout (set tiles): make-thumbnail-classic.py
import json, os, sys, datetime
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageChops
W, H = 1280, 720
GREEN=(112,213,73); SKY=(107,189,255); WHITE=(255,255,255); INK=(2,3,3)
FILES=r"C:\Users\YOURNAME\scoreboard-pipeline"
LOGO1=FILES+r"\team-logo-square.png"
MX, TOP, BOTTOM = 120, 84, H-88          # safe area
BADGE_R = 74          # 2026-10-06: badge in the top-right corner (Kenny: it sat on the VS line)
BADGE_TOP = 54        # top of the green ring; 30 px above the text safe line so it clears the VS rule (Kenny 2026-10-06)
BADGE_BOT = BADGE_TOP + 2*(BADGE_R+6)
RULE_GAP = 34         # min space between the badge ring and the VS rule

def fonts_dir(arg=None):
    for d in [arg, os.path.join(os.environ.get("LOCALAPPDATA",""), r"Microsoft\Windows\Fonts"),
              FILES+r"\_overlay_check\fonts", r"C:\Windows\Fonts"]:
        if d and os.path.exists(os.path.join(d, "Gotham Narrow Bold.otf")): return d
    raise SystemExit("Gotham fonts not found")

def fit_name(d, text, font, maxw, big, small, mn):
    """Return (lines, size). Try 1 line big..small, then 2 lines small..mn, then trim with '…'."""
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
    # last resort: two lines (or one) at the minimum size, trimmed with an ellipsis
    lines = [text] if len(words) == 1 else [" ".join(words[:len(words)//2]), " ".join(words[len(words)//2:])]
    out = []
    for ln in lines:
        while d.textlength(ln, font=font(mn)) > maxw and len(ln) > 1: ln = ln[:-2].rstrip() + "…"
        out.append(ln)
    return out, mn

def main(match, frame, out, fdir=None):
    m=json.load(open(match,encoding="utf-8"))
    t1=(m.get("team1") or "Home Team").upper(); t2=(m.get("team2") or "Opponent").upper()
    try: date=datetime.date.fromisoformat(m["date"]).strftime("%b %d, %Y").upper()
    except Exception: date=""
    FD=fonts_dir(fdir); NB=os.path.join(FD,"Gotham Narrow Bold.otf"); MED=os.path.join(FD,"Gotham Medium.otf")
    f=lambda p,s: ImageFont.truetype(p,s); nb=lambda s: f(NB,s)
    bg=Image.open(frame).convert("RGB"); bw,bh=bg.size
    ch=int(bh*0.80); cw=int(ch*16/9); x0=max(0,(bw-cw)//2)
    bg=bg.crop((x0,0,x0+cw,ch)).resize((W,H),Image.LANCZOS)
    bg=ImageEnhance.Brightness(bg).enhance(0.6)
    g=Image.new("L",(W,H)); gd=ImageDraw.Draw(g)
    for x in range(W): gd.line([(x,0),(x,H)],fill=int(235*max(0,1-x/(W*0.85))))
    bg=Image.composite(Image.new("RGB",(W,H),INK),bg,g)
    b=Image.new("L",(W,H)); bd=ImageDraw.Draw(b)
    for y in range(H-220,H): bd.line([(0,y),(W,y)],fill=int(210*(y-(H-220))/220))
    bg=Image.composite(Image.new("RGB",(W,H),INK),bg,b)
    d=ImageDraw.Draw(bg); L=MX
    # header
    d.rounded_rectangle([L,TOP,L+250,TOP+46],radius=23,fill=GREEN)
    d.text((L+125,TOP+24),"MATCH REPLAY",font=nb(26),fill=INK,anchor="mm")
    d.text((L+272,TOP+24),date,font=f(MED,26),fill=(225,225,225),anchor="lm")
    cx=W-MX-BADGE_R-6
    maxw1=cx-BADGE_R-6-40-L          # our name stops before the badge
    maxw2=W-MX-L                     # opponent row has the full width
    # The tile at the bottom = the tournament / event name (2026-10-06, Kenny: "FINAL" makes no
    # sense on a thumbnail) - <match folder>\event.txt. No event: SCRIMMAGE for a scrimmage,
    # otherwise no tile at all.
    try: event=open(os.path.join(os.path.dirname(os.path.abspath(match)),"event.txt"),encoding="utf-8").read().strip().upper()
    except Exception: event=""
    fmt=event or ("SCRIMMAGE" if (m.get("format") or {}).get("mode")=="open" else "")
    tile_h=76 if fmt else 0
    scale=1.0
    while True:  # re-flow until the block fits between the header and the bottom margin
        l1,s1=fit_name(d,t1,nb,maxw1,int(120*scale),int(84*scale),48)
        l2,s2=fit_name(d,t2,nb,maxw2,int(96*scale),int(70*scale),44)
        lh1,lh2=int(s1*1.02),int(s2*1.02)
        y=TOP+46+50                                   # top of the first name block
        b1=[y+lh1*(i+1)-int(s1*0.2) for i in range(len(l1))]
        vy=b1[-1]+int(30+18*scale)
        y2=vy+int(32+14*scale)
        b2=[y2+lh2*(i+1)-int(s2*0.2) for i in range(len(l2))]
        tile_y=b2[-1]+int(44*scale)+10
        if tile_y+tile_h<=BOTTOM or scale<0.6: break
        scale-=0.05
    # spare room at the bottom -> move the whole block down (up to 50 px) so it sits balanced
    dy=max(0,min(50,BOTTOM-(tile_y+tile_h)))
    b1=[v+dy for v in b1]; b2=[v+dy for v in b2]; vy+=dy; tile_y+=dy
    # long opponent -> rule runs under the badge: keep it RULE_GAP below the ring (push the block
    # down if there's room; otherwise the right-hand rule stops short of the badge)
    nw=max([d.textlength(x,font=nb(s1)) for x in l1]+[d.textlength(x,font=nb(s2)) for x in l2])
    nw=min(nw, W-MX-L)
    under = L+nw > cx-BADGE_R-6-RULE_GAP
    need = BADGE_BOT+RULE_GAP-vy
    if under and need>0:
        extra=max(0,min(need,BOTTOM-(tile_y+tile_h)))
        b1=[v+extra for v in b1]; b2=[v+extra for v in b2]; vy+=extra; tile_y+=extra
    rule_end = L+nw-4
    if under and vy < BADGE_BOT+RULE_GAP: rule_end = min(rule_end, cx-BADGE_R-6-RULE_GAP)
    for i,ln in enumerate(l1): d.text((L,b1[i]),ln,font=nb(s1),fill=GREEN,anchor="ls")
    for i,ln in enumerate(l2): d.text((L,b2[i]),ln,font=nb(s2),fill=WHITE,anchor="ls")
    vf=nb(40); mx=L+nw/2; vw=d.textlength("VS",font=vf)
    d.text((mx,vy),"VS",font=vf,fill=WHITE,anchor="mm")
    d.line([(L+4,vy),(mx-vw/2-24,vy)],fill=(150,150,150),width=3)
    d.line([(mx+vw/2+24,vy),(rule_end,vy)],fill=(150,150,150),width=3)
    tile_y=min(tile_y,BOTTOM-tile_h)
    if fmt:   # green-bordered tile with the event; shrinks (then trims) to stay inside the right margin
        room=W-MX-L-64
        for ts in range(34,21,-2):
            if d.textlength(fmt,font=nb(ts))<=room: break
        while d.textlength(fmt,font=nb(ts))>room and len(fmt)>1: fmt=fmt[:-2].rstrip()+"\u2026"
        lf=nb(ts); lw=d.textlength(fmt,font=lf)
        d.rounded_rectangle([L,tile_y,L+lw+64,tile_y+tile_h],radius=18,fill=(24,26,26),outline=GREEN,width=3)
        d.text((L+32,tile_y+tile_h/2+1),fmt,font=lf,fill=(245,245,245),anchor="lm")
    # our badge in the top-right corner (ring 54 px from the top, 120 px from the right)
    cy=BADGE_TOP+BADGE_R+6
    d.ellipse([cx-BADGE_R-6,cy-BADGE_R-6,cx+BADGE_R+6,cy+BADGE_R+6],fill=GREEN)
    d.ellipse([cx-BADGE_R,cy-BADGE_R,cx+BADGE_R,cy+BADGE_R],fill=INK)
    sz=2*BADGE_R; lg=Image.open(LOGO1).convert("RGB").resize((sz,sz),Image.LANCZOS)
    mk=Image.new("L",(sz,sz)); ImageDraw.Draw(mk).ellipse([0,0,sz-1,sz-1],fill=255)
    bg.paste(lg,(cx-BADGE_R,cy-BADGE_R),mk)
    bg.save(out,quality=92)
    print("saved",out,"| vs line y:",vy,"badge bottom:",BADGE_BOT,"rule end:",int(rule_end),"| name lines:",len(l1),len(l2),"sizes:",s1,s2,"tile bottom:",tile_y+tile_h,"| tile:",fmt or "(none)")

if __name__=="__main__":
    main(*sys.argv[1:5])
