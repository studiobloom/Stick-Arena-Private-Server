# 558 game systems — source-grounded reference

This directory explains how the Ballistick 558 client and this server actually
work, system by system, with every claim tied to the source that proves it.

Nothing here is re-extracted. It is built on the existing workspace:

| input | used for |
| --- | --- |
| `extracted/scripts/as/**` | decompiled ActionScript (the behaviour) |
| `extracted/scripts/pcode/**` | AVM1 listings (authority when AS is ambiguous) |
| `manifests/characters.json` | original SWF ids, export names, frame labels |
| `manifests/relationships.json` | which timeline places which symbol, on which frame |
| `analysis/settings558b.json` | the 558 client's own tuning values |
| `htdocs/stickarena/mapEditorTiles.csv` | tile collision table |
| `ballistickemu/src/**` | the server implementation |
| `htdocs/stickarena/*.php` | the web tier |

Regenerate the machine-readable layer with:

```bash
cd reference/sab558
python scripts/build_systems_index.py
```

That writes `analysis/systems/*.json`, `analysis/visuals/index.html`, and
verifies every source line quoted in `analysis/systems/constants.json`.

## Evidence levels used in these documents

| tag | meaning |
| --- | --- |
| **[C]** | Confirmed: read directly from the cited source line. |
| **[D]** | Derived: computed from confirmed values; the formula is shown. |
| **[U]** | Source-confirmed but runtime-unverified: the code says this, but no client has been run to observe it. |
| **[A]** | Assumption: plausible, not proven; the doc says what would prove it. |

Anything not tagged is **[C]**.

Citation format: `frame_1/DoAction.as:5944` means
`extracted/scripts/as/frame_1/DoAction.as` line 5944. `…/DoAction.as` in a table
is shorthand for the same file. Server citations are repo-relative.

## Conventions

- SWF character ids are the **original** ids from `manifests/characters.json`.
  The decompiler's names (`DefineSprite_2530`, `LIBRARY/Symbol 3268.xml`) are
  shown only where they help you find a file.
- "frame" always means a timeline frame at 34 fps, unless a line says "ms".
- Obfuscated identifiers (`lqkTiW`, `qxdMlq`, `zqyafO`, …) are quoted verbatim.
  They are the only names the client has for those fields; renaming them in the
  text would break the link to the source.

## The systems

| # | system | doc | primary source |
| --- | --- | --- | --- |
| 1 | Player construction, dimensions, animation | [01-player.md](01-player.md) | `frame_1` `stick()`, `animatePlayer()` |
| 2 | Movement and collision | [02-movement-collision.md](02-movement-collision.md) | `ygsfeyb()`, `jhzeUQ()`, `reloadTile()` |
| 3 | Weapons, pickups, attacks, damage | [03-weapons-combat.md](03-weapons-combat.md) | `initializeWeapons()`, `qxTtuh()` |
| 4 | Maps, tile sets, map objects | [04-maps.md](04-maps.md) | `loadArea()`, `generateMapString()` |
| 5 | Health, death, respawn, scoring | [05-health-death-scoring.md](05-health-death-scoring.md) | `damage()`, `endRound()` |
| 6 | Multiplayer synchronisation | [06-multiplayer-sync.md](06-multiplayer-sync.md) | `sendPosition()`, `updatePlayer()` |
| 7 | Lobby, UI, social | [07-lobby-ui-social.md](07-lobby-ui-social.md) | `frame_3`, chat/vote handlers |
| 8 | Runtime verification backlog | [08-runtime-verification.md](08-runtime-verification.md) | — |
| 9 | Runtime evidence (what actually ran) | [09-runtime-evidence.md](09-runtime-evidence.md) | Ruffle 0.7.1 + local harness |

Machine-readable companions:

| file | contents |
| --- | --- |
| `analysis/systems/semantic_index.json` | system → scripts, symbol ids, animations, sounds, settings, server files |
| `analysis/systems/weapons.json` | the 14-weapon table decoded from the AS source, with derived cooldowns |
| `analysis/systems/animations.json` | the 49 weapon-animation labels → clip id → frame count → seconds |
| `analysis/systems/sounds.json` | every `attachSound()` name → character id → extracted file |
| `analysis/systems/tiles.json` | collision types, their rendered shapes, tile-set counts |
| `analysis/systems/constants.json` | named constants with the exact source line each came from |
| `analysis/visuals/index.html` | contact sheets for the player rig, weapons, tiles, FX, UI |
| `runtime/evidence/` | per-scenario screenshots, wire logs and `result.json` |
| `runtime/README.md` | how to run the client locally (Ruffle + harness) |

## Headline facts

- Stage 550×400 at **34 fps**; the game tick is a clip event on the sprite placed
  in `frame_9` that calls `_parent.onFrame("main")` every frame.
- One player = library symbol **`characterMC` (3268)**, attached at runtime.
- HP is **60**; a sledge hit is **80** (one-shot).
- Tiles are **50 px**; the client keeps a **13×10** window of them.
- Collision is movieclip `hitTest` against `tileCol<type>` shapes, not a solver.
- The server **relays** movement and damage; it never simulates them.
- Round time **300 s**, summary **11 s**, ad **20 s** — and the server's
  `RoundTime + 31` in `getSendRoundDetail` is exactly summary+ad.

## Correction log

Defects found while building this reference, and what was changed. Keeping this
list is part of the "confirmed vs assumed" contract.

| date | finding | action |
| --- | --- | --- |
| 2026-11-03 | `swf_inspect.py` decoded `PlaceObject2`/`PlaceObject3` as `Flags, CharacterId, Depth`; the SWF layout is `Flags, Depth, [ClassName], CharacterId`. Every placement edge in `manifests/relationships.json` had the two values swapped. | Parser fixed, `inspect` + manifests regenerated. Consequence: "sprites placed on an authored timeline" is **1,869**, not the 270 that the swapped data suggested. `docs/assets.md` §6, `docs/client-sab558.md` §2.1 and the verification note were corrected. The XFL coverage numbers (222 present / 1,723 missing) were never affected — they come from the `LIBRARY/` file names. |
| 2026-11-03 | The first XFL explanation ("missing symbols are sprites no timeline places") was wrong: 1,867 sprites are reachable from the main timeline, yet only 222 are in the XFL. | Claim replaced with the measured facts and an explicit "decompiler limitation, selection unexplained" statement. |

All 197 source citations in `docs/systems/` were range-checked against the files
they point at; all 39 constants in `analysis/systems/constants.json` are re-read
from their cited line on every build.
