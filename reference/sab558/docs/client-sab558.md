# The 558 client (`sab558.swf`)

Everything in this document is read from the original file by
`scripts/swf_inspect.py` (outputs in `manifests/`) or from the decompiled
ActionScript in `extracted/scripts/as/`. Where a statement is an inference it is
marked **Assumption**.

## 1. Identity and container

| property | value | source |
| --- | --- | --- |
| file | `htdocs/stickarena/sab558.swf` | — |
| SHA-256 | `f86d224501c202fb11c6c681c1ebdd6c2009b27f0a4a645351ad42ebeda3302a` | `manifests/swf_header.json` |
| size | 7,360,142 bytes | `manifests/swf_header.json` |
| signature | `FWS` (uncompressed) | same |
| SWF version | 8 | same |
| ActionScript | AVM1 (ActionScript 1/2): 575 `DoAction`, 83 `DoInitAction`, **no** `DoABC` | `manifests/summary.json` |
| stage | 550 × 400 px = `11000 × 8000` twips, origin (0,0) | `swf_header.json` → `stage_rect_twips` |
| frame rate | 34.0 fps (raw `0x2200` = 8704/256) | `swf_header.json` |
| main timeline | 22 frames (22 `ShowFrame` tags) | `swf_header.json` |
| background | black (`SetBackgroundColor` 00 00 00) | `manifests/tags.json` |
| tags | 9,670 top-level, 77,391 including nested sprite bodies | `manifests/summary.json` |

Cross-check: FFDec's own SWF→XML conversion reports
`version="8" frameCount="22" frameRate="34.0" compression="NONE"` and
`displayRect Xmax="11000" Ymax="8000"`, which matches the independent parser
exactly. `manifests/verification.json` repeats this comparison on every run.

## 2. Character inventory

7,913 characters, keyed by their **original** SWF ids (nothing is renumbered):

| kind | count | extracted to |
| --- | --- | --- |
| `DefineShape` / `2` / `3` / `4` | 1,806 + 115 + 254 + 1,201 = **3,376** | `extracted/shapes/<id>.svg` |
| `DefineSprite` | **1,945** | `extracted/xfl/LIBRARY/Symbol <id>.xml` (222 of them; see §2.1), and `extracted/sprites/DefineSprite_<id>*/<frame>.svg` when the opt-in stage is run |
| `DefineMorphShape` / `2` | 15 + 742 = **757** | `extracted/morphshapes/<id>.svg` |
| `DefineBits` / `JPEG2` / `JPEG3` / `Lossless` / `Lossless2` | 10 + 180 + 675 + 1 + 104 = **970** | `extracted/images/<id>.(jpg\|png)` |
| `DefineEditText` | **470** | `extracted/texts/<id>.txt` |
| `DefineText` | **195** | `extracted/texts/<id>.txt` |
| `DefineButton2` | **100** | `extracted/buttons/`, `extracted/scripts/as/DefineButton2_<id>/` |
| `DefineSound` | **80** | `extracted/sounds/` |
| `DefineFont2` / `3` | 1 + 19 = **20** | `extracted/fonts/` (TTF) and `fonts_woff/` (WOFF) |
| exported symbols (`ExportAssets`) | **1,105 names** | `manifests/characters.json` → `export_names` |
| placement edges (`PlaceObject2/3`) | **9,542** | `manifests/relationships.json` |

Only one tag in the file is not in the public SWF specification: code 255, length
1, at offset 2680. It is recorded in `manifests/summary.json` → `unknowns` and is
left untouched.

### 2.1 Sprites that the XFL project does not contain

Only 222 sprites appear as `LIBRARY/Symbol <id>.xml`; 1,723 do not. The omission
is not explained by timeline reachability or linkage (919 of the missing sprites
carry `ExportAssets` names), so it is a decompiler limitation — see
`docs/assets.md` §6. The missing ones include the whole player rig
(`characterMC` 3268 and its children), which is attached at runtime by
`frame_1/DoAction.as:3861`. They are fully rendered by the opt-in
`sprite_frames` stage (`extracted/sprites/`) and their code is in
`extracted/scripts/as/`.

## 3. Main timeline

The client is a frame-driven state machine. Confirmed labels (`FrameLabel` tags,
`manifests/swf_header.json` → `main_timeline_frame_labels`):

| frame | label | notes |
| --- | --- | --- |
| 1 | — | bootstrap: config/version/asset loading, socket creation |
| 2 | `titleFrame` | title screen |
| 3 | `lobbyFrame` | lobby / room list |
| 4 | `profileFrame` | player profile |
| 5 | `shopFrame` | shop |
| 6 | `mapEditorFrame` | map editor |
| 7 | `preMain` | pre-game |
| 8 | — | transition |
| 9 | `mainFrame` | in-game |
| 10 | `deathFrame` | death |
| 11 | `optionsFrame` | options |
| 12 | `reportFrame` | report / tattle |
| 13 | `roundSummaryFrame` | round summary |
| 14 | `creditsFrame` | credits |
| 15 | `preReturnFrame` | |
| 16 | `prePirateFrame` | |
| 17 | `tasvfsdfveg1` | obfuscated label, purpose not stated in the file |
| 18 | `postPirateFrame` | |
| 19 | `exportFrame` | **asset batch**: 478 sprites, 726 shapes, 476 exports, 330 JPEG3 |
| 20 | `postExportFrame` | single `ShowFrame` + `DoAction` |
| 21 | `exportFrameB` | **asset batch**: 805 sprites, 641 shapes, 467 exports |
| 22 | `postExportFrameB` | single `ShowFrame` + `DoAction` |

Confirmed by tag offsets: the `exportFrame` label sits at byte 2,635,591 and
its asset block runs to the `postExportFrame` label at 5,242,720; `exportFrameB`
starts at 5,242,740 and runs to `postExportFrameB` at 7,360,119 (the end of the
file). In other words the Ballistick asset pack is appended inside the main
timeline rather than shipped as a separate SWF. Frames 20 and 22 carry only a
label, a few `RemoveObject2` tags, one `DoAction` and one `ShowFrame`; the real
content is the definitions that precede them.

Note on numbering in `manifests/tags.json`: `frame` is "the frame being built",
so tags that follow the last `ShowFrame` (here only the final `End` tag) are
reported as frame 23.

Per-frame placement (which character ids are placed on the main timeline) is in
`manifests/relationships.json` filtered on `timeline == 0`.

## 4. Scripts

`extracted/scripts/as/` (decompiled source) and `extracted/scripts/pcode/`
(AVM1 listings) contain **1,273 script units**, named by their original scope:

```
frame_1/DoAction.as                                  main timeline, frame 1
frame_2/PlaceObject2_357_58/CLIPACTIONRECORD ...as    clip event on a placed sprite
DefineSprite_237/frame_2/DoAction.as                 sprite timeline
DefineSprite_237/frame_2/PlaceObject2_236_3/...as    sprite child clip event
DefineButton2_1313/...                               button handlers
DoInitAction.as                                      top-level DoInitAction
<ClassName>.as, __Packages/mx/...                    AS2 classes
```

Confirmed class content: the client ships the Flash MX component set
(`mx.controls.*`, `mx.core.*`, `mx.managers.*`, `mx.skins.*`) plus
`com.meychi.ascrypt.MD5` (an MD5 implementation) — see
`extracted/scripts/as/__Packages/`.

Confirmed bootstrap constants (all in `frame_1/DoAction.as`):

| literal / code | line | meaning |
| --- | --- | --- |
| `var uonhbfsw = 558;` | 8305 | build number, used to compose `settings558b.ini` and `upgradevalues558.ini` |
| `var mapVersionNum = 558;` | 8306 | map set version (→ `maps/558/`) |
| `var gameVersion = "1." + uonhbfsw + " (FP 8) BLSK";` | 8365 | title-bar version string |
| `var ijsjfnsdjfu = "Hx09TdCC62Nwln1P";` | 8307 | 16-char literal passed to `sendCheckServerCapacity()` — it is the `08` capacity key (runtime-confirmed, see §7) |
| `sendDataSettings.sendAndLoad(localFilePath + "settings" + uonhbfsw + "b.ini", ...)` | 3326 | loads the 558 settings file over HTTP POST |
| `sendDataUpgradeValues.sendAndLoad(localFilePath + "upgradevalues" + uonhbfsw + ".ini", ...)` | 3532 | loads the 558 price table |

## 5. Network entry points used by the client

All of these are string literals in the SWF (`manifests/as2_strings.json`), and
this build has already been repointed at `127.0.0.1`:

| URL literal | served by | purpose |
| --- | --- | --- |
| `http://127.0.0.1/version_check.php` | `htdocs/stickarena/version_check.php` | version gate, POST `ver=558` |
| `http://127.0.0.1/stick_arena.php` | `htdocs/stickarena/stick_arena.php` | account creation (`action=create`) and player report (`action=report_player`); login is over the socket, not HTTP |
| `http://127.0.0.1/api.php?` | `htdocs/stickarena/api.php` | map list/get/save, account methods |
| `http://127.0.0.1/com/languagefilter.ini` | `htdocs/stickarena/com/languagefilter.ini` | profanity filter |
| `http://127.0.0.1/ballistick/eula.dat`, `.../faq.dat` | static | legal / FAQ text |
| `http://127.0.0.1/maps/` | `htdocs/stickarena/maps/558/` | map data |
| `http://127.0.0.1/mapEditorTiles.csv` | `htdocs/stickarena/mapEditorTiles.csv` | editor tile definitions |
| `http://127.0.0.1/ballistick/ingame/*.swf` | `htdocs/stickarena/ballistick/ingame/` | shop / lab-pass UI modules |
| `http://127.0.0.1/stickarena/highscore.php` | `htdocs/stickarena/stickarena/highscore.php` | highscore link |

The socket is a plain `XMLSocket` (`frame_1/DoAction.as:4755`) whose host/port
come from the server list in `settings558b.ini`. Protocol details are in
[`protocol.md`](protocol.md).

## 6. Settings the client reads (`settings558b.ini`)

Parsed to `analysis/settings558b.json`. Confirmed sections include:

- `DEFAULT CONTROLS` — `sKUp0..2`, `sKAttack*`, `sKChat*`, … (key codes).
- `MAP LIST BY CYCLE ORDER` — `sMap0..N`, plus `sMapCompat0..19` and
  `nNumClassicMapsCompat=15`.
- `SERVER LIST` — `sServerName0/URL0/Type0/Locale0`, `sConnectPort0` (two entries
  in the shipped file: `BallistickEMU` at `127.0.0.1:1138`, and the retail
  `ballistick6.xgenstudios.com`).
- `GAMEPLAY VALUES` — `sPlayerAcc=3`, `sPlayerMaxVel=9`, `sMaxNumPlayers=6`,
  `sMaxNumPlayersNoPass=4`, `sMaxMsgLen=45`, `sMaxMsgLenLobby=135`,
  `sMaxArenaLen=20`, `sCollisionCheckGhost=1`, …
- `DEFAULT OPTIONS` — quality, language filter, particles, blood, crosshair.
- Name generators for quickstart players (`sF0..`, `sL0..`).

`upgradevalues558.ini` (`analysis/upgradevalues558.json`) holds the 558 spinner
and item prices, e.g. `sSpinnerCost0=120` … `sSpinnerCost20=2700`,
`nNumFreeSpinners=10`.

## 7. Open questions (not answered by the file)

- ~~**Assumption:** `ijsjfnsdjfu` is the RC4 key for map payloads.~~ **Resolved
  (2026-11-04).** Runtime capture shows the client sends `08Hx09TdCC62Nwln1P` on
  every connect (`sendCheckServerCapacity(serverNum, ijsjfnsdjfu)`, four call
  sites at `:4764-4783`). The string is the capacity key. Separately,
  `class.rc4crypt.php` is `require_once`d by `stick_arena.php` but never
  instantiated anywhere in the web tier, and no map payload is encrypted on the
  wire, so the RC4 reading was wrong.
- **Assumption:** frames 19–22 are a build-merge artefact of the Ballistick asset
  update. The labels and the tag layout support it, but no build metadata in the
  file states it.
- The meaning of the obfuscated frame label `tasvfsdfveg1` (frame 17) is not
  stated anywhere in the file.
