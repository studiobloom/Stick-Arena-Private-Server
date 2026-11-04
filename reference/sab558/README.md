# Ballistick 558 reference workspace

A reproducible, evidence-first workspace around **Stick Arena: Ballistick 558**.

| | |
| --- | --- |
| Target client | `htdocs/stickarena/sab558.swf` |
| SHA-256 | `f86d224501c202fb11c6c681c1ebdd6c2009b27f0a4a645351ad42ebeda3302a` |
| Size | 7,360,142 bytes, uncompressed (`FWS`), SWF version 8, AVM1 (ActionScript 1/2) |
| Stage | 550 × 400 px (`11000 × 8000` twips), 34 fps, 22 main-timeline frames |
| Out of scope | `sab588.swf`, `dimensions.swf`, `maps/563`, `maps/593`, `*588*.ini`, `*598*.ini` |

Rules for working here live in [`../../AGENTS.md`](../../AGENTS.md). Read that
first: it is strict about 558-only evidence and about never modifying originals.

## Layout

```
reference/sab558/
├── source/          identity record of the original SWF (hash, size, capture time)
├── scripts/         the extraction pipeline and manifest builders (bash + stdlib Python)
├── extracted/       decompiled assets            (generated, git-ignored)
├── manifests/       JSON/CSV indexes + verification results   (tracked)
├── analysis/        generated inventories, string index, extraction report (tracked)
├── docs/            architecture / client / protocol / asset documentation (tracked)
└── logs/            per-stage decompiler logs   (generated, git-ignored)
```

## Reproduce everything

Requirements (already present on this machine, nothing is installed by the pipeline):

- JPEXS Free Flash Decompiler **26.4.0 nightly build 3604** (`ffdec-cli.exe`),
  found at `C:\Program Files (x86)\FFDec\ffdec-cli.exe`, on `PATH`, or via `FFDEC=`.
- Java 8 runtime (the one FFDec is installed against).
- Python 3.8+ (standard library only — no pip packages).
- Bash (Git for Windows).

```bash
cd reference/sab558
./scripts/extract_sab558.sh                 # ~3 min, ~120 MB of assets
./scripts/extract_sab558.sh --verify-only   # re-hash + rebuild manifests only
./scripts/extract_sab558.sh --with-sprite-frames   # + every sprite frame (23,998 SVG, ~1.6 GB, ~6.5 min)
./scripts/extract_sab558.sh --with-swf-xml         # + full SWF->XML dump (~65 MB)
```

Useful flags: `--list`, `--only inspect,scripts_as`, `--skip xfl`, `--force`.

Every run:

1. hashes the original SWF and writes `source/SHA256SUMS` + `source/SOURCE.txt`;
2. runs each stage in its own scratch directory and records status/duration in
   `logs/stages.jsonl`;
3. rebuilds `manifests/export_manifest.json` + `coverage.json`;
4. re-hashes every extracted file in `verify_extraction.py` and writes
   `manifests/verification.json` + `analysis/extraction_report.md`;
5. re-hashes the original SWF and fails if it changed.

## Stages

| stage | output | what it is |
| --- | --- | --- |
| `inspect` | `manifests/*.json` | independent binary parse: header, tag tree, characters, placement edges, AVM1 string literals |
| `tags_dump` | `analysis/ffdec_dumpSWF.txt` | FFDec's tag listing, used as a second opinion |
| `scripts_as` | `extracted/scripts/as/` | decompiled ActionScript source |
| `scripts_pcode` | `extracted/scripts/pcode/` | AVM1 P-code listings (authoritative for behaviour) |
| `shapes` | `extracted/shapes/` | every `DefineShape*` as SVG |
| `morphshapes` | `extracted/morphshapes/` | every `DefineMorphShape*` as SVG |
| `images` | `extracted/images/` | embedded JPEG/PNG bitmaps, original bytes where possible |
| `sounds` | `extracted/sounds/` | `DefineSound` audio (MP3/WAV) |
| `fonts_ttf`, `fonts_woff`, `font4` | `extracted/fonts/`, `fonts_woff/`, `font4/` | embedded fonts |
| `text` | `extracted/texts/` | static text + `DefineEditText` contents |
| `binary` | `extracted/binaryData/` | `DefineBinaryData` blobs (none in this SWF) |
| `symbolclass` | `extracted/symbolClass/symbols.csv` | ExportAssets / SymbolClass linkage table |
| `buttons` | `extracted/buttons/` | button states |
| `frames` | `extracted/frames/` | the 22 authored main-timeline screens as PNG |
| `xfl` | `extracted/xfl/` | XFL project: per-symbol timelines, layers, vectors, library items |
| `sprite_frames` | `extracted/sprites/` | every frame of every sprite as SVG (opt-in) |
| `swf_xml` | `extracted/swf_xml/sab558.xml` | FFDec's complete SWF→XML dump (opt-in, ~65 MB) |

## Where to look for what

| question | file |
| --- | --- |
| What is in the SWF? | `manifests/summary.json`, `manifests/characters.json` |
| What does a specific character id contain? | `manifests/characters.json` |
| Which sprite places which character, on which frame? | `manifests/relationships.json` |
| Which extracted file came from which SWF id? | `manifests/export_manifest.json` / `.csv` |
| What strings/URLs are in the client? | `manifests/as2_strings.json`, `manifests/as2_strings.txt` |
| Is the extraction complete? | `manifests/verification.json`, `analysis/extraction_report.md` |
| Which repo files are 558 vs other versions? | `analysis/repo_inventory.json` / `.md` |
| Parsed 558 config | `analysis/settings558b.json`, `analysis/upgradevalues558.json` |
| **Game systems (start here)** | `docs/systems/README.md` |
| Player rig, animation | `docs/systems/01-player.md` |
| Movement, collision | `docs/systems/02-movement-collision.md` |
| Weapons, damage | `docs/systems/03-weapons-combat.md` |
| Maps, tile sets | `docs/systems/04-maps.md` |
| Health, death, scoring | `docs/systems/05-health-death-scoring.md` |
| Multiplayer sync | `docs/systems/06-multiplayer-sync.md` |
| Lobby, UI, social | `docs/systems/07-lobby-ui-social.md` |
| Runtime verification backlog | `docs/systems/08-runtime-verification.md` |
| Machine-readable system index | `analysis/systems/semantic_index.json` |
| Visual contact sheets | `analysis/visuals/index.html` |
| Client architecture | `docs/client-sab558.md` |
| Toolchain (JPEXS) | `docs/toolchain.md` |
| Server/web/database architecture | `docs/architecture.md` |
| Socket protocol | `docs/protocol.md` |
| Asset naming + how to trace an id | `docs/assets.md` |
| Recommended next steps | `docs/next-steps.md` |

## Build the systems reference

The extraction is the input; the systems reference is derived from it and can be
rebuilt independently:

```bash
cd reference/sab558
python scripts/build_systems_index.py
```

It parses the weapon table out of the ActionScript, joins the animation labels to
their clip ids, resolves every `attachSound()` name, reads the tile collision
table, and **re-reads every source line it quotes** — a wrong line number or a
missing symbol aborts the build instead of producing a plausible-looking index.
Output: `analysis/systems/*.json` and `analysis/visuals/index.html`.

## Ground rules (short version)

- The original SWF, server and web files are read-only inputs. The pipeline
  proves this by hashing before and after.
- `extracted/` is derived output. Never hand-edit it; fix the pipeline instead.
- Every claim in `docs/` is either **Confirmed** with a pointer to evidence, or
  explicitly labelled **Assumption**.
- No 588 / Dimensions material is used, compared against, or mixed in.

## What is tracked in git

`scripts/`, `docs/`, `source/`, the small manifests and the analysis files are
reviewable deliverables and are tracked. `extracted/`, `logs/` and the large
generated manifests (`tags.json`, `export_manifest.*`, `as2_strings.json`,
`ffdec_dumpSWF.txt`) are git-ignored because they are reproducible in one
command — see `../../.gitignore`.
