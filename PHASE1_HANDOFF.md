# PHASE 1 HANDOFF — Stick Arena: Ballistick 558

Status: **Phase 1 complete** (extraction, static analysis, semantic reference,
client-side runtime verification). No further gameplay research is in scope.

Target: `htdocs/stickarena/sab558.swf`
SHA-256 `f86d224501c202fb11c6c681c1ebdd6c2009b27f0a4a645351ad42ebeda3302a`
(verified unchanged after every run).

---

## 1. Quick start

```bash
# 1. rebuild the extracted assets (needs JPEXS, see §5)
cd reference/sab558 && ./scripts/extract_sab558.sh --verify-only

# 2. rebuild the semantic systems index + visual sheets
python scripts/build_systems_index.py

# 3. run the original client against the local harness (optional)
bash runtime/tools/fetch_runtime.sh
python runtime/harness/run_scenario.py quickstart
```

Read first: `AGENTS.md` (rules), `reference/sab558/README.md` (workspace),
`reference/sab558/docs/systems/README.md` (game systems index).

---

## 2. Repository map

Two zones, never mixed:

```
<repo root>
├── PHASE1_HANDOFF.md          this document
├── AGENTS.md                  rules for anyone (human or agent) working here
├── README.md                  upstream project README (original, untouched)
├── htdocs/                    ORIGINAL web tier + the 558 client      READ-ONLY
│   └── stickarena/sab558.swf  the extraction target
├── ballistickemu/             ORIGINAL Java server                    READ-ONLY
├── Import database/           ORIGINAL MySQL schema + seeds          READ-ONLY
└── reference/sab558/          GENERATED / ANALYSIS / EVIDENCE
    ├── source/                SWF identity record (hash, size, capture time)
    ├── scripts/               extraction + manifest + index tooling
    ├── extracted/             all decompiled assets        (git-ignored)
    ├── manifests/             machine-readable indexes     (mostly tracked)
    ├── analysis/              inventories, string index, systems JSON, report
    ├── docs/                  hand-written documentation
    ├── runtime/               Ruffle + harness + evidence
    └── logs/                  per-stage decompiler logs    (git-ignored)
```

Original files are inputs only. The pipeline hashes the SWF before and after
every run and fails if it changed.

---

## 3. Where to find what

| I need… | Go to |
| --- | --- |
| The original client | `htdocs/stickarena/sab558.swf` |
| The original server | `ballistickemu/src/ballistickemu/**` |
| The original web tier | `htdocs/stickarena/*.php`, `api.php`, `settings558b.ini`, `upgradevalues558.ini`, `maps/558/**` |
| The database schema | `Import database/ballistick_struct.sql` |
| **Extracted assets** | `reference/sab558/extracted/` — see `docs/assets.md` for naming |
| **Animation references** | `analysis/systems/animations.json` (49 weapon labels → clip id → duration), `extracted/sprites/` (23,998 frame SVGs), `extracted/xfl/` |
| **Gameplay documentation** | `docs/systems/01`…`07` (player, movement, weapons, maps, health, sync, lobby) |
| **Networking documentation** | `docs/protocol.md` (wire protocol), `docs/systems/06` (sync model) |
| **Runtime evidence** | `runtime/evidence/<scenario>/` and `docs/systems/09-runtime-evidence.md` |
| **Client architecture** | `docs/client-sab558.md` |
| **Server/web architecture** | `docs/architecture.md` |
| **Extraction quality report** | `analysis/extraction_report.md`, `manifests/verification.json` |
| **Visual contact sheets** | `analysis/visuals/index.html` (open in a browser) |
| **What is still unverified** | `docs/systems/08-runtime-verification.md` |

---

## 4. Regenerating from a fresh clone

`extracted/`, `logs/` and the four largest manifests are git-ignored, so a fresh
clone has the tooling but not the assets. Regenerate them:

```bash
cd reference/sab558
./scripts/extract_sab558.sh                  # ~3 min, ~120 MB
```

Options:

| flag | effect |
| --- | --- |
| `--verify-only` | re-hash every extracted file, rebuild manifests, write the report |
| `--with-sprite-frames` | also render all 23,998 sprite frames (~1.6 GB, ~7 min) |
| `--with-swf-xml` | also dump the full SWF→XML (~65 MB) |
| `--force` | re-run stages instead of reusing complete ones |
| `--list`, `--only a,b`, `--skip a,b` | stage control |

Then the semantic layer:

```bash
python scripts/build_systems_index.py        # analysis/systems/*.json + visuals
```

The builder re-reads every source line it quotes and aborts on a bad citation or
an unknown symbol id — a green run means the index still matches the sources.

---

## 5. Requirements (nothing is installed system-wide)

| tool | why | where |
| --- | --- | --- |
| JPEXS Free Flash Decompiler **26.4.0 nightly 3604** | all decompilation | `C:\Program Files (x86)\FFDec`, on `PATH`, or `FFDEC=` |
| Java 8 runtime | runs FFDec | present |
| Python 3.8+ (stdlib only) | manifests, index, harness | present |
| Bash (Git for Windows) | pipeline | present |
| Ruffle **0.7.1** | runtime verification only | fetched by `runtime/tools/fetch_runtime.sh` (checksum-pinned, in-repo) |

The pipeline never installs anything and never writes outside
`reference/sab558/`.

---

## 6. Authoritative sources per system

Machine-readable manifests (`reference/sab558/manifests/`):

| manifest | authority for |
| --- | --- |
| `swf_header.json` | stage size, frame rate, frame count, compression, SWF version, frame labels |
| `tags.json` | every tag with byte offset, depth, timeline, frame (25 MB, git-ignored) |
| `characters.json` | character id → kind, export names, frame counts, frame labels |
| `relationships.json` | which timeline places which character on which frame |
| `as2_strings.json` / `as2_strings.txt` | every AVM1 string literal + location |
| `export_manifest.json` / `.csv` | extracted file → original character id + sha256 |
| `coverage.json` | expected vs extracted per kind, unresolved ids |
| `verification.json` | all verification checks |
| `ffdec_version.txt` | pinned decompiler build |

Derived analysis (`reference/sab558/analysis/systems/`):

| file | authority for |
| --- | --- |
| `semantic_index.json` | system → scripts, symbol ids, animations, sounds, server files |
| `weapons.json` | the 14-weapon table decoded from `initializeWeapons()` + derived cooldowns |
| `animations.json` | `gfoKHPq` (2530) label table → clip id → frames → seconds |
| `sounds.json` | every `attachSound()` name → character id → file (and the 7 that fail) |
| `tiles.json` | collision types 0–9, their rendered shapes, tile-set counts |
| `constants.json` | 39 named constants, each re-read from its cited source line |

Per-system authoritative sources:

| system | code | doc |
| --- | --- | --- |
| Player rig / animation | `extracted/scripts/as/frame_1/DoAction.as` (`stick()`, `animatePlayer()`), symbols 3268/1767/2530 | `docs/systems/01` |
| Movement / collision | `frame_1` `ygsfeyb/jhzeUQ/ehbdybe/move/reloadTile` | `docs/systems/02` |
| Weapons / damage | `frame_1` `initializeWeapons/qxTtuh/damage/qkZPDc` | `docs/systems/03` |
| Maps | `frame_1` `loadArea`, `frame_6` `generateMapString` | `docs/systems/04` |
| Health / death / scoring | `frame_1` `damage/tqkYQT/spawn/endRound/startNextRound` | `docs/systems/05` |
| Multiplayer sync | `frame_1` `send*`, `socketCalls`, `updatePlayer`; `StickRoom`/`PacketHandlerGame` | `docs/systems/06`, `docs/protocol.md` |
| Lobby / UI / social | `frame_3`, `frame_1` chat/mod handlers | `docs/systems/07` |

---

## 7. Verified behaviour (runtime)

Run against the **original client** under Ruffle 0.7.1 and a local test double.
Artifacts: `runtime/evidence/<scenario>/` (`result.json`, `packets.log`,
screenshots). Details: `docs/systems/09-runtime-evidence.md`.

| verified | value |
| --- | --- |
| Boot + config load order | `version_check.php?ver=558` → settings/upgrade/language/tiles |
| Capacity handshake | `08Hx09TdCC62Nwln1P` |
| Login → lobby | `09 1234;1234` → `A…` → `0c`, `01`, `03_` |
| Run / walk speed | **4.94** / **2.24** px per frame (168.9 / 76.1 px/s) |
| Collision response | velocity reflects (`× −0.5`) on wall contact |
| Two clients, one room | join + mutual position packets (318 each way) |
| Combat | **victim-side damage**: 12 × 5 = 60 HP → death → respawn **4.38 s** |
| Kill text | rendered from the ini's `sKillTextPre/Post` table |
| Server echo | required; without it the client drops after `sServerTimeout` (10 s) |
| Round clock | **server-authoritative** (constant server time ⇒ round never ends) |
| Sound linkages | 3 of 7 unresolved names confirmed missing (`dragVolume`, `flamethrowerimp00`, `railgunimp00`) |

### Test-double limitations (important)

`runtime/harness/stub_server.py` is **not** the Java server. It is a test double
whose packet formats are transcribed from `StickPacketMaker.java` with source
line comments. Therefore:

- "verified" above means **client behaviour against a protocol-faithful stub**;
- the stub accepts **any** credentials — login tests do not validate
  authentication policy;
- it implements no MySQL persistence, no lab-pass/VIP logic, no moderation, no
  round arbitration, no map storage;
- Ruffle is a Flash **emulator**; four case-mismatched sound linkages resolved in
  Ruffle and stay inconclusive (Adobe Flash is case-sensitive).

Test-only deviations, all confined to `runtime/http/` and documented in
`docs/systems/09-runtime-evidence.md` §9.3: `sAutoQuickStart=1`/`sSkipIntro=1`
(the client's own `TEMP DEV VALUES` switches), `sEnforcePerformance=0` for the
long round run, and shared-spawn copies of the 20 classic maps
(`make_test_maps.py`; only `&sp=` differs). The repository's original files are
never modified.

---

## 8. Unresolved original-server behaviour (NOT verified)

These need the real Java server with MySQL + PHP; none of that ran here.

| # | behaviour | status |
| --- | --- | --- |
| S1 | Authentication policy, `users` table, bans, IP bans, ticket timers | unverified — blocker (no MySQL) |
| S2 | Lab-pass / VIP room visibility and joining | unverified — blocker (no MySQL) |
| S3 | Vote-kick enforcement and room blacklisting | unverified — blocker (no MySQL) |
| S4 | Round arbitration (`updateStats(getWinner())`, 300→−1→−30) | unverified — blocker |
| S5 | Map save/load through `api.php` + `maps` table | unverified — blocker (no PHP/MySQL) |
| S6 | `stick_arena.php` stats (and its missing `report_player` branch) | unverified — blocker |
| S7 | Error codes `42`/`5` reaching the client | unverified — testable with the stub |
| S8 | Client `0e`/`0k`/`T` opcodes vs server dispatch | unverified — testable with the stub |
| S9 | Spawn-protection window (`jhIqSQ`, 133.3 frames) | unverified — easy stub test |
| S10 | Ghost/spectator mode (`collisionCheckGhost`, `ghostAlpha`) | unverified |
| S11 | Spinner/pet two-colour tinting | unverified |
| S12 | Map `rt`/`ts` with non-default values | unverified |
| S13 | Full 300 s round + 11 s summary + 20 s ad, end to end | unverified — client's 120 s inactivity watchdog blocks idle automation |

---

## 9. Generated files, tools, reproducibility

| path | tracked | reproducible by |
| --- | --- | --- |
| `reference/sab558/extracted/` | no (git-ignored) | `scripts/extract_sab558.sh` |
| `reference/sab558/logs/` | no | same |
| `manifests/tags.json`, `export_manifest.*`, `as2_strings.json`, `analysis/ffdec_dumpSWF.txt` | no (large) | `--verify-only` |
| other manifests, `analysis/systems/*`, `analysis/visuals/index.html` | yes | `swf_inspect.py` / `build_systems_index.py` |
| `runtime/tools/ruffle/`, `runtime/state/` | no | `runtime/tools/fetch_runtime.sh` |
| `runtime/evidence/*/packets.log` | no | re-run a scenario |
| `runtime/evidence/*/result.json`, `notes.md`, screenshots | yes | `run_scenario.py` |

`.gitignore` covers all of the above explicitly; nothing generated leaks into
tracked paths.

### Corrections made during Phase 1 (do not re-introduce)

1. `PlaceObject2/3` field order is `Flags, Depth, CharacterId` — an early parser
   had it reversed and produced wrong placement edges. Fixed; manifests rebuilt.
2. The walk key is **V** (`sKWalk0=118`), not W.
3. `ijsjfnsdjfu` is the `08` capacity key; the RC4 claim was retracted
   (`class.rc4crypt.php` is required but never used).
4. The XFL library is partial (222 of 1,945 sprites) and the selection is not
   explained by reachability or linkage — treat it as a decompiler limitation.

---

## 10. Final state

- Extraction verification: **PASS** — 35,394 files / 1.75 GB re-hashed, 0 missing,
  0 size/hash mismatches, one documented warning (XFL coverage).
- Semantic index: builds clean; 7 systems, 197 source citations range-checked,
  39 constants re-read from source.
- Original SWF SHA-256 unchanged.
- No original client, server, web or database file was modified.
- Working tree: 4 untracked entries (`.gitignore`, `AGENTS.md`,
  `PHASE1_HANDOFF.md`, `reference/`) = 119 files / ~18 MB if committed.
- HEAD: `ee90efd21415bfd9e2ceddaa38221475230a1f90` (upstream `main`).
- Nothing was committed, per the "never commit unless asked" rule. To pin the
  handoff: `git add .gitignore AGENTS.md PHASE1_HANDOFF.md reference/ && git commit -m "sab558 phase 1 reference workspace"`.
