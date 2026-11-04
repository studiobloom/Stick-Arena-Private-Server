# 2. Movement and tile collision

Movement is a small velocity integrator. Collision is **not** a tile solver: the
client keeps a movieclip layer containing one collision shape per visible tile
and hit-tests the player against it, reflecting velocity on contact.

## 2.1 Input

Keys are read through `keyIsDownMulti()` (`frame_1/DoAction.as:736-752`), which
checks the three key codes bound to each action in `settings558b.ini`
(`sKUp0..2`, `sKDown0..2`, …). The shipped bindings are
`analysis/settings558b.json` → `DEFAULT CONTROLS`.

`stick.prototype.move()` builds the 2-character `facing` string
(`frame_1/DoAction.as:9300-9351`):

| key | `facing` |
| --- | --- |
| D (right) | `"20"` |
| A (left) | `"01"` |
| W (up) | `"10"` |
| S (down) | `"02"` |
| D + S | `"22"` |
| A + S | `"21"` |
| D + W | `"12"` |
| A + W | `"11"` |

The walk key is **V**, not W. `this.walk = keyIsDownMulti("W")` (`:9302-9311`)
looks up the `kW[]` array, which `loadSettings` fills from `sKWalk0..2`:
`118` (`v`), `86` (`V`), `220`. The letter in the function is a slot name, not a
key name.

> **Runtime check (2026-11-04, Ruffle 0.7.1).** Holding `V` produced
> `walk=1` in the client's `1` packets; holding `W` did not. This corrects an
> earlier reading of this document that said "W is the walk key".

There is no separate run key: not holding V is "run". `facing` is only rebuilt
while `mod` is `walk` or `stand` (`:9288`), so an attacking or dead player keeps
the last direction.

## 2.2 The integrator

`ygsfeyb(dir, walk, movement, xVel, yVel, w)`
(`frame_1/DoAction.as:5944-6002`):

```actionscript
if(_loc5_ != "0" && _loc6_ != "0") {          // diagonal
   _loc3_ = Math.min(Math.sqrt(Math.pow(player.lqkTiW * weapons[w].walkingSpeed,2) * 2)
                     * 0.00376 * frameDeltaTime, player.lqkTiW * 3);
   _loc4_ = Math.min(Math.sqrt(Math.pow(player.maxVel * weapons[w].walkingSpeed,2) * 2)
                     * 0.00376 * frameDeltaTime, player.maxVel * 3);
} else {                                       // straight
   _loc3_ = Math.min(player.lqkTiW * weapons[w].walkingSpeed * frameDeltaTime / 133,
                     player.lqkTiW * 3);
   _loc4_ = Math.min(player.maxVel * weapons[w].walkingSpeed * frameDeltaTime / 133,
                     player.maxVel * 3);
}
```

`_loc3_` is the acceleration applied this frame, `_loc4_` the speed ceiling.
Then, per axis, `if(v < _loc4_) v += _loc3_` in the requested direction
(`:5963-5987`), followed by:

```actionscript
if(walk) { xVel *= player.qkKZwi; yVel *= player.qkKZwi; }   // 0.7
xVel *= friction;  yVel *= friction;                          // 0.65
```

— `:5992-5999`. The walk multiplier is applied **before** friction, so walking
scales the whole velocity, not just the acceleration.

| symbol | value | source |
| --- | --- | --- |
| `player.lqkTiW` (accel) | **3** | `:2874`, from `sPlayerAcc=3` |
| `player.maxVel` | **9** | `:2875`, from `sPlayerMaxVel=9` |
| `player.qkKZwi` (walk) | **0.7** | `:2876` |
| `friction` | **0.65** | `:8502` |
| `frameDeltaTime` | measured over 4 frames | `:1390-1396` |

`[D]` `frameDeltaTime` is the time for **4** frames (set in
`calculateFrameRate()`, which `onFrame` calls when `mainCount >= 4`, `:2932-2936`).
At 34 fps it is ≈ 117 ms, so at 30 fps it would be 133 and `dt / 133` = 1.

`[D]` Steady state of `v ← (v + a) · f` is `v = a·f/(1−f)`:

| mode | per-frame speed | px/s at 34 fps | measured (runtime) |
| --- | --- | --- | --- |
| run, no weapon penalty (`ws = 1`) | 4.9 | ≈ 167 | **4.94 px/frame, 168.9 px/s** |
| walk (`×0.7`) | 2.2 | ≈ 75 | **2.24 px/frame, 76.1 px/s** |
| sledge / shotgun / chaingun / ak47 (`ws = 0.7`) | 3.4 | ≈ 117 | not measured |

The runtime figures come from the client's own `xVel*1000` / `yVel*1000` fields
in its `1` packets, best free run over four directions
(`runtime/evidence/movement/result.json`). They match the derived steady state to
within 1.5 %, which also confirms `frameDeltaTime ≈ 117 ms` (4 frames at 34 fps)
and friction 0.65 as used above.

Diagonal acceleration is `√2` times the straight value, so the resulting *speed
vector magnitude* matches the straight-line speed — the normalisation is exact.

`[U]` Because `frameDeltaTime` is a measured 4-frame delta while the integrator
runs every frame, the effective acceleration depends on frame pacing. The
steady-state numbers above assume a stable 34 fps.

## 2.3 Velocity classification

`ehbdybe(xVel, yVel, mod, movement)` (`frame_1/DoAction.as:6034-6055`):

```actionscript
if(Math.abs(xVel) < 0.2) xVel = 0;
if(Math.abs(yVel) < 0.2) yVel = 0;
vel = Math.sqrt(xVel*xVel + yVel*yVel);
if(vel < 0.8)            mod = "stand";
else if(movement)        mod = "walk";
```

So `mod` is `stand` below 0.8 px/frame, `walk` above it, and the legs animation
uses `vel` as its phase input (see [01](01-player.md) §1.2).

## 2.4 Collision

`jhzeUQ(x, y, xVel, yVel)` (`frame_1/DoAction.as:6002-6034`) probes the
collision layer `xqXvQHh.c` at **±6 px** on the leading edge, per axis:

```actionscript
if(xVel > 0) {
   if(xqXvQHh.c.hitTest(x + xVel + 6, y + 6, true) ||
      xqXvQHh.c.hitTest(x + xVel + 6, y - 6, true)) xVel *= -0.5;
}
```

and symmetrically for left, down and up (the up case probes `y + yVel - 6 - 1`).
Consequences, all confirmed:

- collision is **per axis**, so a blocked X does not zero Y — the player slides;
- the response is a **reflection at half speed** (`× -0.5`), not a stop;
- the probe box is **12 × 12 px** around the player origin, independent of the
  24.3 × 54.65 body art;
- the up probe is 1 px further out than the others (an authored asymmetry).

`xqXvQHh.c` is a 13 × 10 grid of slots, each holding a `tileCol<type>` clip
(`reloadTile`, `frame_1/DoAction.as:484-514`). The shapes are real artwork, so
collision is whatever the artist drew — including slopes and one-way ledges.

## 2.5 Tile collision types

`manifests/characters.json` exports ten collision symbols, `tileCol0` …
`tileCol9`. Their rendered bounds (from
`extracted/sprites/DefineSprite_*_tileCol*/1.svg`) define what each type blocks:

| type | symbol id | size (px) | extent inside the 52 px cell | meaning |
| --- | --- | --- | --- | --- |
| 0 | 5025 | 0 × 0 | — | no collision |
| 1 | 7475 | 52 × 51.1 | full, 0.4 px inset | full block (alternate art) |
| 2 | 5024 | 0 × 0 | — | no collision |
| 3 | 5034 | 52 × 52 | full | full block — **also blocks projectiles** |
| 4 | 5032 | 52 × 52 | full | full block — used for map borders |
| 5 | 5026 | 52 × 38.5 | top 38.5 px | partial (upper 74 %) |
| 6 | 5031 | 52 × 26 | top 26 px | upper half |
| 7 | 5029 | 52 × 13.5 | top 13.5 px | upper quarter |
| 8 | 5030 | 26 × 26 | top-left quarter | quarter block |
| 9 | 5028 | 52 × 52 | full | full block (separate art, id 5027) |

The only type with *behavioural* meaning in code is **3**: the projectile raycast
stops when it hits `earth[x][y][3] == 3` (`frame_1/DoAction.as:4136`). Every other
type is purely the shape that gets hit-tested.

`loadArea()` forces the map's outer ring to type **4**
(`frame_1/DoAction.as:6414-6417`), so the border always blocks.

Frequency in the shipped 558 map set (811 editor tiles,
`htdocs/stickarena/mapEditorTiles.csv`):

| type | 0 | 1 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tiles | 292 | 1 | 227 | 89 | 11 | 99 | 30 | 40 | 22 |

## 2.6 Camera and world window

`stick.prototype.move()` scrolls the world container `xqXvQHh` when the player
leaves a dead zone (`frame_1/DoAction.as:9412-9467`):

| bound | value | field |
| --- | --- | --- |
| left | **250** | `player.zqZLsy` (`:2894`) |
| right | **300** | `player.kkjecK` (`:2895`) |
| top | **175** | `player.qxOLFJ` (`:2896`) |
| bottom | **225** | `player.lqbwJm` (`:2897`) |

The overshoot is divided by `scrollSpeed` (**6**, from `sScrollSpeed=6`) and
subtracted from the world position, so the camera eases rather than snapping. The
world is clamped to `earthMinX/earthMaxX` (set in `loadArea`, `:6450-6451`).

`updateEarth()` (`:532-585`) decides which way to shift the window: if the world
origin moves past `-50 + 50*lqVyUC` (or `50*lqVyUC`) it steps one column; the row
case is analogous. `reloadTile(x,y)` maps a world tile to a window slot with
`tX = x mod 13`, `tY = y mod 10`, slot name `tile<tX*100+tY>`
(`:484-495`), so the visible set is **13 columns × 10 rows = 130 slots** for a
550 × 400 stage at 50 px per tile.

`[D]` 13 × 50 = 650 px and 10 × 50 = 500 px, i.e. one tile of margin on each axis
around the 550 × 400 viewport — enough that the player never sees the window edge
before `updateEarth` shifts it.

## 2.7 Cross-reference: the server does not move players

`ballistickemu/src/ballistickemu/Game/handlers/GamePacketBroadcastHandler.java:30`
re-broadcasts opcodes `1/2/4/5/6/8` to the room verbatim. There is no server-side
position, collision or physics. Consequences:

- a modified client can move anywhere; nothing validates it;
- the server cannot arbitrate a "who hit whom" dispute;
- `StickRoom` tracks only membership, map, cycle mode and round time.

## 2.8 Open questions

- `[U]` The ±6 px probe combined with a 24.3 px wide body means the visual body is
  wider than its collision box. Whether players visibly clip into walls depends
  on tile art; needs observation.
- `[A]` `earthMinX/earthMaxX` clamping is intended to keep the window inside the
  map, but the exact boundary behaviour (does the camera stop at the map edge?)
  was not traced through `updateEarthCol/Row`.
- `[U]` Collision type 1 is used by exactly **one** editor tile but exists as a
  distinct 52 × 51.1 shape; which tile that is, and why, is not documented.
