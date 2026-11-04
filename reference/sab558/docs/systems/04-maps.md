# 4. Maps, tile sets and map objects

A 558 map is a **plain-text record file**, not a binary blob. The client
serialises and parses exactly the same format, and `maps/558/*.dat` in this repo
is that format. This document specifies it from the two functions that define it:
`loadArea()` (`frame_1/DoAction.as:6390-6474`) and `generateMapString()`
(`frame_6/DoAction.as:223-269`).

## 4.1 File format

```
inf=<cols:2> <rows:2> <name> &tiles=\r
<cell> <cell> ... (cols*rows cells, space separated, one record)
\r&sp=<x:4> <y:4> ... (8 pairs)
\r&ws=<x:4> <y:4> <weapon:4> <delay:4> ... (8 groups)
\r&rt=<roundTime:4>
\r&ts=<tileSet:1>
```

Confirmed byte-for-byte against `htdocs/stickarena/maps/558/__xgenhq.dat`
(6,184 bytes):

| field | observed | parser |
| --- | --- | --- |
| `inf` | `inf=35 24 XGen HQ       ` | `areaWidth = int(metaData.substr(0,2))`, `areaHeight = int(metaData.substr(3,2))`, name = `substr(6)` (`:6393-6398`) |
| `tiles` | 840 tokens = 35 × 24 | cells are read at `i*7 + j*width*7 + 2`, 6 chars each (`:6401-6412`) |
| `sp` | 8 × 10 chars | `x = substr(0,4)`, `y = substr(5,4)` (`:6421-6433`) |
| `ws` | 8 × 20 chars | `x = substr(0,4)`, `y = substr(5,4)`, `weapon = substr(10,4)`, `delay = substr(15,4)` (`:6435-6450`) |
| `rt` | ` 300` | `roundTime = Number(substr(0,4))` (`:6399`) |
| `ts` | `0` | `tileSet = Number(substr(0,1))` (`:6400`) |

Records are separated by **CR** (`\r`), not LF. The writer emits
`"&tiles=\r"` and `"\r&sp="` (`frame_6/DoAction.as:230-252`), and the reader
splits on the `&`-prefixed keys (`loadCustomArea`, `:6330-6344`).

`[C]` The `7 chars per cell` stride includes the trailing space separator, and
the parser skips two characters before the first cell (`+2`). In the custom-map
path the client prepends a space to the text after `tiles=`, and that text starts
with a carriage return, so the two skipped characters are exactly `" " + CR`
(`loadCustomArea`, `:6337-6338`).

## 4.2 Tile cell encoding

Each cell is 6 characters:

| chars | field | meaning |
| --- | --- | --- |
| `0..2` | graphic id | `tile<set><letter><n>` sprite, e.g. `0C0` → `tile0C0` |
| `3` | rotation | 0–3, multiplied by 90° (`earth[x][y][1] * 90`) |
| `4` | mirror | 0–3; bit 1 = flip X, bit 2 = flip Y (`tMir`, `:514-532`) |
| `5` | collision | 0–9 → `tileCol<type>` (see [02](02-movement-collision.md) §2.5) |

Example from `__xgenhq.dat`: `0C0003` = graphic `0C0`, rotation 0, no mirror,
collision **3** (full block, blocks bullets).

The client stores it as `earth[x][y] = [graphic, rotationIndex, mirrorIndex,
collisionType]` (`:6405-6409`). `reloadTile()` then attaches
`tile<graphic>` into the visual layer and `tileCol<collision>` into the collision
layer for the matching window slot (`:484-514`).

`[C]` `loadArea` overwrites the collision type of the outer ring with **4**
regardless of what the file says (`:6414-6417`), so map borders always block.

## 4.3 Spawns

**Player spawns** — 8 entries, 10 characters each: `x` (4), space, `y` (4),
space. An entry is skipped if both are `0` (`:6421-6433`). `spawn()` picks
`random(playerSpawnPoints)` (`:9192`), so spawn order in the file does not
matter.

**Weapon spawns** — 8 entries, 20 characters each:

| chars | field |
| --- | --- |
| 0–3 | x (pixels) |
| 5–8 | y (pixels) |
| 10–13 | weapon id (0–13, see [03](03-weapons-combat.md)) |
| 15–18 | respawn delay in **seconds**; the client multiplies by 1000 (`:6445`) |

The initial timer is set to **3000 ms** for every spawn (`:6446`), so all
pickups appear 3 s after the map loads and then respawn after their own delay.

## 4.4 Round time and tile set

- `rt` — round time in seconds, read into `zqotxw.roundTime`. The editor always
  writes `300` (`frame_6/DoAction.as:259-261`), and the client also has
  `sRoundTime=300` in `settings558b.ini`; the map value wins for a map that
  specifies one.
- `ts` — tile set index 0–5. Values `< 4` use a flat background
  (`opaqueBackground = 0`); `4` and `5` use a parallax background sprite
  `parallaxBG<ts>` (`spawn()`, `:9169-9180`).

`[C]` `maps/558/__xgenhq.dat` has `&ts=0`, so the classic maps use the flat
background.

## 4.5 Map index space

`mapNum` is a single character in the map-cycle string. Decoding is
`charToNumCaseSensitive` = `charCode - 55` for letters, `charCode - 48` for digits
(`frame_1/DoAction.as:11-19`), i.e. `0-9` → 0–9, `A-Z` → 10–35, and beyond that
it simply continues through ASCII (`a` → 42, …). It is **not** base-36.

| `mapNum` | meaning | list | source |
| --- | --- | --- | --- |
| 0–30 | stock map | `mapList[]` ← `sMap0..30` (31 entries) | `:6310-6313`, `:7067-7077` |
| 31–41 | custom map slot | `api.php` slot `mapNum - 31` | `:6314-6316`, `:7081-7083` |
| ≥ 42 | feature map | `featureMapList[]` ← `sFeatureMap0..25` (26 entries) | `:7078-7080` |

`[C]` The custom range is wider than the UI: `maxMapSlots = 5`
(`frame_1/DoAction.as:8652`), so only slots 0–4 (mapNum 31–35) are offered even
though 31–41 is reserved.

`[C]` In compatibility server mode the client uses `mapListCompat[]`
(`sMapCompat0..19`, 20 entries) and `numClassicMapsCompat = 15`
(`:4616-4630`, `:7275-7284`).

Shipped map sets on disk (`htdocs/stickarena/maps/558/`):

| directory | `.dat` files | referenced by |
| --- | --- | --- |
| root | 20 | `sMap0..19` (classic) |
| `ballistick/` | 11 | `sMap20..30` |
| `feature/` | 41 | `sFeatureMap0..25` references 26 of them |
| **total** | **72** | |

`[C]` 15 of the 41 feature maps are on disk but not in the 26-entry cycle list.

## 4.6 Map cycle string

The cycle is a string of map-index characters, e.g. `"0A3"`. The first character
is the current map. `startNextRound()` rotates it
(`frame_1/DoAction.as:7058-7062`):

```actionscript
mapCycleList = mapCycleList.substr(1).concat(mapCycleList.substr(0,1));
mapNum = charToNumCaseSensitive(mapCycleList.substr(0,1));
sendSetRoomVariable("mp=" + mapCycleList);      // opcode 05
```

The list is built in `getMapCycleList()` (`:4606-4723`) from four checkboxes —
classic, Ballistick, custom, feature — and is limited to `sMaxArenaLen=20`
entries. Room creation sends it with opcode `02` (`:1648`).

## 4.7 Loading paths

| source | mechanism | citation |
| --- | --- | --- |
| stock map | `LoadVars.sendAndLoad(localFilePath + "maps/" + mapVersionNum + "/" + fileName)` | `:6362-6389` |
| custom map | `LoadVars.sendAndLoad(apiURL + "method=xgen.stickarena.maps.get&username=…&slot_id=…")`, then XML walk | `:6319-6360` |
| editor save | `LoadVars.data = generateMapString()`, POST to `method=xgen.stickarena.maps.save&…&slot_id=…&name=…` | `frame_6/DoAction.as:181-223` |

`mapVersionNum = 558` (`frame_1/DoAction.as:8306`), so stock maps always come
from `maps/558/`.

## 4.8 Tile sets

`htdocs/stickarena/mapEditorTiles.csv` is the editor's tile catalogue, in the
same `&key=value` dialect as the ini files. It has **811 tiles** across 6 sets:

| set | tiles | notes |
| --- | --- | --- |
| 0 | 149 | classic |
| 1 | 99 | |
| 2 | 183 | |
| 3 | 154 | |
| 4 | 199 | parallax background (`ts >= 4`) |
| 5 | 27 | |

Each row is `_<set><letter><n>,rotation,mirroring,collision`. The SWF exports 608
`tile<set><letter><n>` sprites; the rest of the catalogue reuses graphics with
different rotation/mirror/collision.

`[C]` Collision values in the catalogue are 0–9 and their frequency is in
[02](02-movement-collision.md) §2.5. Only 1 of the 811 tiles uses collision
type 1.

## 4.9 Editor constraints

| constraint | value | source |
| --- | --- | --- |
| min width | 15 tiles | `sEditorMinTilesWide` |
| min height | 11 tiles | `sEditorMinTilesHigh` |
| max width | 40 tiles | `sEditorMaxTilesWide` |
| max height | 40 tiles | `sEditorMaxTilesHigh` |
| max map slots | 5 | `maxMapSlots` (`:8652`) |
| tile page size | 52 px grid, `tileSetsWidth × tileSetsHeight` | `frame_6/DoAction.as:965-975` |

`[C]` The `inf` field is only two characters wide, so the **file format** can
express at most 99 × 99; the editor's 40 × 40 cap is a UI limit, not a format
limit.

## 4.10 Cross-reference: the server and the web tier

| layer | what it does with maps | citation |
| --- | --- | --- |
| server | stores map id + cycle mode + cycle list per room; never parses map data | `Types/StickRoom.java:45-62` |
| server | relays map-cycle get/set | `Lobby/handlers/MapCycleRequestHandler.java`, `Game/handlers/SetMapCycleListHandler.java` |
| server | accepts map ratings (opcode `0i`) | `Game/handlers/MapRatingHandler.java` |
| web | `xgen.stickarena.maps.list/get/save` on the `maps` table (`userid`, `slot_id`, `name`, `mapdata`) | `htdocs/stickarena/api.php`, `Import database/ballistick_struct.sql` |
| web | proxies list/get to `api.xgenstudios.com` when the local user has no maps and `getMapsXGenServer` is true | `api.php:40-95` |

`[C]` The server's round time is a separate constant (`StickRoom.RoundTime = 300`,
reset to 300 at −30); it never reads the map's `rt`.

## 4.10.1 Test fixture: shared-spawn maps

`runtime/harness/make_test_maps.py` writes test copies of the 20 classic maps to
`runtime/http/maps/558/` in which all eight `&sp=` slots point at the map's own
first spawn point. Only that section differs; tiles, weapon spawns, `rt` and `ts`
are byte-identical to the originals (verified by diffing everything except the
`&sp=` span).

It exists so two clients can be spawned on the same tile for combat testing.
The harness serves these copies instead of `htdocs/stickarena/maps/558/`, which
is never modified. If a test needs real spawn distribution, delete
`runtime/http/maps/` and the harness falls back to the repository files.

## 4.11 Open questions

- `[A]` `&rt=` is confirmed as "round time" by `loadArea`, but no shipped map
  uses a value other than 300, so the client's behaviour with e.g. `rt=120` is
  unverified (does the round timer honour it? `updateRoundTimer` counts down from
  `tqJqPc = roundTime + summary + ad`, which suggests yes).
- `[U]` Whether the server ever tells clients a different round time; it sends
  `RoundTime + 31` in `getSendRoundDetail`, and the client subtracts
  `summary + ad` again, so the map's `rt` only matters for the first round.
- `[A]` The `&rt=` field width is 4 characters, so values ≥ 10000 s are not
  expressible.
