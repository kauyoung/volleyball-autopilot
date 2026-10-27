# Fusion scoreboard build — FINAL

Frosted bar · club colours · sets columns · serve ball · set pill.
Built for a **4K (3840×2160) timeline**. All positions and sizes below are proportional (0–1), so Fusion scales them automatically — the only pixel-based values are noted where they appear.

![The finished scoreboard node graph in Resolve's Fusion page, as build-scoreboard.lua builds it: the background and text nodes along the bottom feed a left-to-right chain of Merge nodes ending at MediaOut1](fusion-node-graph.png)
<sub>The finished graph as `build-scoreboard.lua` builds it (click to enlarge). Each element is its own node feeding one long left-to-right chain of Merges; the seven nodes the script keys from the match file are listed [near the end](#the-seven-nodes-the-script-drives).</sub>

---

## Club colours

| Colour | Hex | Fusion R / G / B | Used for |
|---|---|---|---|
| Club green | `#70D549` | `0.439` / `0.835` / `0.286` | Team 1 accent bar |
| Club black | `#020303` | `0.008` / `0.012` / `0.012` | bar + pill background |
| Opponent blue | `#0A84FF` | `0.039` / `0.518` / `1.0` | opponent accent bar |

---

## Two things that make Fusion make sense

1. **Nodes flow left to right.** The last one is `MediaOut1` — whatever reaches it is what you see.
2. **Merge nodes stack images.** **Orange** input = background, **green** input = drawn on top. Every new element needs its own Merge.

**Add a node:** `Shift + Space` → type name → Enter
**Rename:** click it → `F2`

> **Fusion's Y axis runs upward** — `0` is the bottom of frame, `1` is the top. That's why the bar sits at Y `0.115`.

> **Positions are starting points.** Get things roughly placed, then drag in the viewer. Two minutes of dragging beats recalculating.

---

## Step 1 — Create the composition

1. **Edit** page → **Effects Library** → **Effects** → **Fusion Composition**
2. Drag onto track **V2**, above your footage; stretch to span the match
3. With it selected, click the **Fusion** tab

You'll see one node: `MediaOut1`. Everything sits on transparency, so Resolve composites it over the video.

---

## Step 2 — The bar  ⟵ *build this, then stop and check*

1. Add `Background` → Color tab:
   - Type **Solid Color**, Color R `0.008` G `0.012` B `0.012`
   - **Alpha `0.74`** ← the translucency
   - Rename `BarBG`
2. Add `Rectangle` → drag its output into `BarBG`'s **blue triangle** (Effect Mask) input → rename `BarShape`

| Setting | Value |
|---|---|
| Width | `0.75` |
| Height | `0.115` |
| Center X | `0.5` |
| Center Y | `0.115` |
| Corner Radius | `0.15` |

3. Connect `BarBG` → `MediaOut1`

**✋ Checkpoint — a soft dark rounded bar should appear over your footage.** If it does, everything after this is the same pattern repeated.

---

## Step 3 — Score cell + dividers

**3a. Lighter cell behind the scores**
1. `Background` → white, Alpha `0.055` → rename `ScoreCellBG`
2. `Rectangle` → blue input → rename `ScoreCellShape`
   - Width `0.134`, Height `0.115`, Center X `0.5`, Center Y `0.115`, Corner Radius `0`
3. Merge onto `BarBG`

**3b. Centre hairline** (between the two scores)
1. `Background` → white, Alpha `0.22` → rename `ScoreDivider`
2. `Rectangle` → blue input → Width `0.0006`, Height `0.072`, Center X `0.5`, Center Y `0.115`
3. Merge on

**3c. Two cell separators** (either side of the score cell)
Same recipe, white at Alpha `0.10`, Width `0.0005`, Height `0.115`, Center Y `0.115`
- `SepLeft` at Center X `0.433`
- `SepRight` at Center X `0.567`

---

## Step 4 — Team accent bars

**Left:** `Background` → club green, Alpha `1.0` → rename `AccentLeft`
`Rectangle` → blue input → Width `0.0016`, Height `0.052`, Center X `0.1335`, Center Y `0.115`, Corner Radius `1.0`

**Right:** `Background` → opponent blue → rename `AccentRight`
`Rectangle` → Width `0.0016`, Height `0.052`, Center X `0.8665`, Center Y `0.115`, Corner Radius `1.0`

Merge each on.

---

## Step 5 — Text

Add each with `Shift + Space` → `Text+`. **Text** tab for content/font/size, **Layout** tab for position.

All: font **Segoe UI** or **SF Pro Text**, weight **Semibold**, **tabular figures on** if available.

| Rename to | Text | Size | Colour | Center X | Center Y | Align |
|---|---|---|---|---|---|---|
| `Team1Name` | Home Team | `0.030` | white | `0.147` | `0.115` | Left |
| `Team2Name` | Opponent | `0.030` | white | `0.853` | `0.115` | Right |
| `Team1SetsLabel` | SETS | `0.011` | white 45% | `0.406` | `0.132` | Centre |
| `Team1Sets` | 0 | `0.030` | white | `0.406` | `0.106` | Centre |
| `Team2SetsLabel` | SETS | `0.011` | white 45% | `0.594` | `0.132` | Centre |
| `Team2Sets` | 0 | `0.030` | white | `0.594` | `0.106` | Centre |
| `Team1Score` | 0 | `0.054` | white | `0.466` | `0.115` | Centre |
| `Team2Score` | 0 | `0.054` | white | `0.534` | `0.115` | Centre |

**On the SETS labels:** set **Tracking to about `0.14`** in the Text tab. Wide tracking on a small caption is what stops it crowding the number beneath — it's the single detail that makes this pair look considered rather than cramped.

**Sentence case for team names** — "Home Team", not "HOME TEAM".

Merge each on.

---

## Step 6 — Serve ball

Don't draw the seams with masks — import the icon instead.

1. Save `volleyball-serve-icon.png` somewhere permanent — **not** your Downloads folder, since a Loader breaks if the file moves. Something like `C:\Users\<you>\Documents\Resolve Assets\` works well.
   - It's 512×512 with a transparent background, which is ample for the ~43px it renders at in 4K
2. Add a `Loader` node → point it at the PNG → rename **`Team1Serve`**
3. Add a `Transform` after it → Size `0.02`, Center X `0.365`, Center Y `0.115`
4. Merge on, and set that Merge's **Blend to `0.0`** (hidden by default)
5. Repeat for **`Team2Serve`** at Center X `0.635`

The ball sits at a fixed position on the inner edge of each team block, so it never shifts as team names change length.

---

## Step 7 — Set pill

1. `Background` → club black, Alpha `0.74` → rename `PillBG`
2. `Rectangle` → Width `0.05`, Height `0.024`, Center X `0.5`, Center Y `0.038`, Corner Radius `1.0`
3. Merge on
4. `Text+` → rename **`SetNumber`**
   - Text `SET 1`, Size `0.014`, white 70%, Tracking `0.10`, Center X `0.5`, Center Y `0.038`, Centre aligned
5. Merge on

---

## Step 8 — Drop shadow

Add a `Drop Shadow` node between your final Merge and `MediaOut1`.
Softness **`16`**, Opacity `0.45`, slight downward offset.

> Softness is measured in **pixels**, not proportionally — that's why it's 16 here rather than the 8 you'd use on a 1080p timeline. If you ever switch timeline resolution, this is the one value to revisit.

---

## Step 9 — One dial for overall size

Add a `Transform` node just before the Drop Shadow. Its **Size** parameter now scales the entire scorebar as one unit.

If the bar feels too big or small over real footage, change that one value instead of editing twenty nodes.

---

## Step 10 — Save as a template

1. `Ctrl + A` in the node graph → right-click → **Group**
2. **Edit** page → Media Pool → right-click → **New Power Bin**
3. Drag the Fusion Composition clip into it

Every future match starts with one drag.

---

## The seven nodes the script drives

| Node | What changes | When |
|---|---|---|
| `Team1Score` | live score | every point |
| `Team2Score` | live score | every point |
| `Team1Sets` | sets won | at set end |
| `Team2Sets` | sets won | at set end |
| `SetNumber` | SET 1 → SET 2 → SET 3 | at set end |
| `Team1Serve` | Blend 0 ⇄ 1 | when serve changes |
| `Team2Serve` | Blend 0 ⇄ 1 | when serve changes |

**Static, typed once per match:** `Team1Name`, `Team2Name`
Names must match **exactly** — the script finds nodes by name.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Nothing in the viewer | Final node isn't connected to `MediaOut1` |
| Background fills the screen | Rectangle isn't in the **blue** Effect Mask input |
| New element hides everything | Merge inputs swapped — previous goes in **orange** |
| Text overlaps | Sizes too large — reduce, then drag to reposition |
| Text invisible | Its Merge sits *before* the bar; move it after |
| Bar not translucent | `BarBG` Alpha is `1.0` — set `0.74` |
| Both serve balls showing | Their Merge Blend must start at `0.0` |
| Bar too wide/narrow overall | Change the Step 9 Transform Size, not individual nodes |
