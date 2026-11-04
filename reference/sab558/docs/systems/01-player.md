# 1. Player construction, dimensions and animation

A player is not a single sprite with a frame per pose. It is a **container
symbol** (`characterMC`, id 3268) with separate clips for the body, the arm and
weapon, the name tag, the death effect and the spawn effect. The client attaches
that container at runtime and drives its children from ActionScript.

## 1.1 The rig

The symbol is used two ways:

1. **The local player's visible rig** is a *timeline instance* of `characterMC`
   placed on main-timeline frame 9 (`mainFrame`) with instance name `gxqKQk`
   (`analysis/ffdec_dumpSWF.txt`: `PlaceObject3 (chid: 3268, dpt: 7, nm: "gxqKQk")`).
   All local movement and animation code addresses `gxqKQk` directly.
2. **Every player slot gets a runtime copy** in the world container:

```actionscript
xqXvQHh.attachMovie("characterMC","player" + a + "MC",lId + 3000);
```

— `frame_1/DoAction.as:3861` (`addPlayer`). `lId` is a free slot `0..5`
(`maxNumPlayers`), so the container depth is `3000 + slot`. Slot 0 is the local
player's own copy: it is created invisible (`_alpha = 0; _visible = false`) and
`player.id = a` is assigned to it (`:3866-3873`). It exists so that the ghost /
authoritative-position path (`collisionCheckGhost`) has a world-space clip to
read for the local player, and so remote-facing code can address every player
uniformly as `xqXvQHh.player<uid>MC`.

The container's children, read from the rendered rig
(`extracted/sprites/DefineSprite_3268_characterMC/1.svg`, which names every
instance) and cross-checked against `manifests/characters.json`:

| instance name | id | rendered size | role |
| --- | --- | --- | --- |
| `fqBEfG` | 1767 | 24.3 × 54.65 | **body**: 3-frame state clip (`idle`, `walk`, `run`) |
| `legs` (inside `fqBEfG`) | 972 | 24.3 × 27.95 | idle legs |
| `gfoKHPq` | 2530 | 317.7 × 671.15 | **arm + weapon**: 49 labelled frames, one set per weapon |
| `gfyeOfn` | 3032 | 254.4 × 254.4 | spawn/ghost body, hidden by `spawnDone()` |
| `deathMC` | 3249 | 269.3 × 269.25 | death overlay |
| `dieMC` | 3076 | 77.95 × 82.25 | 78-frame death animation |
| `soulHellMC` | 3017 | 122.6 × 160.65 | 58-frame death soul effect |
| `soulHeavenMC` | 3257 | 516.6 × 176.1 | 52-frame spawn soul effect |
| `colorMC` | 1755 | — | colour-transform holder |
| `nameMC` | 3263 | 176.95 × 20 | name plate (`nameText`, `nameText2/3/4`, `nameTextC`) |
| `textMC` | 3267 | 81.95 × 111.8 | id / local-slot / ping text (`idText`, `localIdText`, `pingText`) |

**Player dimensions.** The body is **24.3 × 54.65 px** and the idle legs
**24.3 × 27.95 px**. Those are the authored artwork bounds. They are *not* the
collision box: movement collision probes at ±6 px around the container origin
(`frame_1/DoAction.as:6002-6034`, see [02](02-movement-collision.md)), i.e. a
12 × 12 px probe.

The arm/weapon clip is much larger than the body because it contains every
weapon's swing/aim pose; its 317 × 671 bounds are the union of all attack arcs,
not a hitbox. The actual hit area is a separate child, `gxfpoCYV.fqgFvkCAnev`
(`frame_1/DoAction.as:4121`).

## 1.2 State machine

`animatePlayer(mc, mod, walk, vzeCpU, w, f, vel, facing, inv)`
(`frame_1/DoAction.as:6055-6172`) drives the rig from four inputs: movement
class `mod`, the W key (`walk`), the current weapon id (`w`) and speed `vel`.

| condition | body clip | legs | citation |
| --- | --- | --- | --- |
| `mod == "walk"` and `walk` (W held) | `fqBEfG.gotoAndStop("walk")` | `legs.gotoAndStop(int(f))`, `f += vel / 3.5`, wrap at **40** | `:6058-6075` |
| `mod == "walk"` and not walking | `fqBEfG.gotoAndStop("run")` | `f += vel / 9`, wrap at **18** | `:6076-6096` |
| `mod == "stand"` | `fqBEfG.gotoAndStop("idle")` | `f = 6` (fixed) | `:6097-6112` |
| any | body rotation = `smoothRot(..., getTargetRotation(facing), 1.5)` | | `:6113-6116` |
| `inv` (spawn protection) | `_alpha += 25`, wraps 0..100 → flicker | | `:6117-6131` |
| not local and `ghostAlpha == 0` | `_visible = false` | | `:6144-6152` |

`[D]` The leg cycle is speed-coupled, not time-coupled: at 34 fps a running
player at `vel = 5.6` advances `f` by `0.62` per frame, so one 18-frame run cycle
takes ≈ 29 frames ≈ 0.85 s. Walking (`vel ≈ 2.5`) advances `f` by `0.71` per
frame over a 40-frame cycle ≈ 56 frames ≈ 1.65 s.

The arm clip is switched by label, not by frame number:

```actionscript
gfoKHPq.gotoAndStop(weapons[w].idleAnim + "Idle");   // standing
gfoKHPq.gotoAndStop(weapons[w].runAnim  + "Idle");   // moving
gfoKHPq.gotoAndStop(weapons[w].attackAnim + "Attack" + rnd);
```

— `frame_1/DoAction.as:6065`, `:6088`, `:9247`. The label table lives in
`gfoKHPq` (2530) and has **49 labels** (see [03](03-weapons-combat.md) §3.4).

`[D]` `smoothRot(cRot, tRot, 1.5)` moves 1/1.5 = 66.7 % of the remaining angle
per frame when the delta exceeds 2°, so a 180° turn completes in ~5 frames.

## 1.3 Facing and rotation

`facing` is a 2-character string, `[vertical][horizontal]`, where `1` = up/left,
`2` = down/right and `0` = none — built in `stick.prototype.move()`
(`frame_1/DoAction.as:9307-9351`):

| keys | `facing` |
| --- | --- |
| right | `"20"` |
| down-right | `"22"` |
| down | `"02"` |
| up-left | `"11"` |
| none | unchanged (`vzRquP = false`) |

`getTargetRotation(facing)` is `rotArray[Number(trim(facing))]`
(`frame_1/DoAction.as:1087-1090`). The table is complete and confirmed
(`frame_1/DoAction.as:8221-8229`):

| facing | rotation | facing | rotation |
| --- | --- | --- | --- |
| `"10"` (up) | 0° | `"20"` (right) | 180° |
| `"12"` (up-right) | 45° | `"21"` (down-left) | 225° |
| `"02"` (down) | 90° | `"01"` (left) | 270° |
| `"22"` (down-right) | 125° | `"11"` (up-left) | 315° |

Note the two asymmetries in the original data: down-right is **125°**, not 135°,
and the table has no entry for `"00"` (no direction), so an idle player keeps the
last rotation. The arm clip additionally aims at the mouse every frame
(`frame_1/DoAction.as:9372-9376`), which is why the weapon points at the cursor
independently of the body.

## 1.4 Spawn, death and protection

| state | what happens | citation |
| --- | --- | --- |
| spawn | `gotoAndStop("mainFrame")`, `mod="spawn"`, `vwcSqZ = qxCihK` (full HP), random map spawn point, `sendSpawn(x,y)`, `spawnFX`, `animateSpawn("Local")` | `frame_1/DoAction.as:9159-9201` |
| spawn end | `spawnDone()` hides `gfyeOfn`, shows `fqBEfG` and `gfoKHPq`, `mod="walk"` | `:9201-9208` |
| protection | `jhIqSQ = true`, `zqbcal = 133.3`; counts down 1 per frame; while true the player cannot be hit (`if(!player.jhIqSQ)` in `qxTtuh`) | `:2887`, `:4101` |
| protection cut | picking up any weapon does `zqbcal -= 66.6` | `:9212` |
| death | `tqkYQT()` → `deathFX`, `addToDeaths(1)`, `mod="dead"`, `kkPTHf = 150` | `:9127-9159` |
| respawn | while `mod == "dead"`, `kkPTHf` decrements 1 per frame; at ≤ 0 → `spawn()` | `:9485-9491` |

`[D]` 150 frames at 34 fps ≈ **4.4 s** dead time; 133.3 frames ≈ **3.9 s** spawn
protection (≈ 2.0 s if a weapon is picked up immediately).

The decrement is `Math.max(1, int(frameDeltaTime / 4 / 33.3))`
(`frame_1/DoAction.as:9486`). `frameDeltaTime` is measured over 4 frames
(`calculateFrameRate`, `:1390-1396`), so at 34 fps it is ≈117 and the expression
evaluates to `int(0.88) = 0 → max(1,0) = 1`. It is effectively **frame-counted,
not time-counted**. `[U]` At very low frame rates it becomes >1 per frame; the
exact switch-over has not been observed.

## 1.5 Customisation: spinner, pet, colours

Each player carries two colour pairs and two cosmetics:

| field | meaning | citation |
| --- | --- | --- |
| `spinners[]` | `{num, red0, green0, blue0, red1, green1, blue1}` | `frame_1/DoAction.as:2855` |
| `pets[]` | same shape, defaults black | `:2856` |
| `zqtPAS` / `qxXTym` | selected spinner / pet index | `:2857-2858` |

Rendering (`frame_1/DoAction.as:4497-4508`):

- spinner → `indicatorMC<NN>` (NN = spinner number, 2 digits), child
  `subIndicatorMC.colorMC0/colorMC1` tinted with the two colours at alpha 75;
- pet → `petBehavior<behaviour>MC` (behaviour from `petBehavior[]`, an ini array)
  with child `petMC<NN>`, scaled by `petScale` and tinted at alpha 100.

Remote players get the same treatment in `changePlayerColor()`
(`frame_1/DoAction.as:4312-4343`), which is driven by the `U` game-state packet
(see [06](06-multiplayer-sync.md)). The colour pair is also sent to the server at
login (`LoginHandler.java:99-115` builds a 9-character `rrrgggbbb` string).

`[U]` `petScale` and `petBehavior[]` come from `settings558b.ini`; the shipped
values are in `analysis/settings558b.json` but their visual effect has not been
observed.

## 1.6 Cross-reference: what the server knows about a player

| server side | content |
| --- | --- |
| `LoginHandler.java:99-130` | name padded to 20 with `#`, colour `rrrgggbbb`, kills, deaths, wins, losses, rounds, lab pass, expiry, ticket, cash, level |
| `StickPacketMaker.getLoginSuccess` (`:155-186`) | the `A` packet carrying those fields |
| `StickPacketMaker.getClientInfo` (`:187-212`) | `U` packet: uid, name, colour, kills, deaths, wins, losses, rounds, pass, level |
| `Types/StickClient.java` | server-side session state (spinner, pet, room, mod status) |

The server never stores the rig state (facing, velocity, animation frame) — that
exists only on clients and is broadcast, not persisted.

## 1.7 Open questions

- `[U]` Why `"22"` (down-right) maps to 125° rather than 135° is not explained
  anywhere in the source. It may compensate for an asymmetric sprite origin.
- `[U]` `ghostAlpha` (spectator/ghost rendering) is set from the options screen;
  its default value was not traced.
- `[U]` Whether `petBehavior[]` contains exactly the 7 exported behaviours
  (`petBehaviorFloatMC` 6332, `CircleFast/Slow/Small` 6644-6646,
  `CounterCircleFast/Slow/Small` 6647-6649) is not verified against the ini.
