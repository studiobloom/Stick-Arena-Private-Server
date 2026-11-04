# Extracted assets: layout, naming, and how to trace them

## 1. Directory layout

```
extracted/
├── scripts/as/            ActionScript source, one file per script unit
├── scripts/pcode/         the same units as AVM1 P-code listings
├── shapes/                <id>.svg                    (DefineShape, 2, 3, 4)
├── morphshapes/           <id>.svg                    (DefineMorphShape, 2)
├── images/                <id>.jpg | <id>.png         (DefineBits*, DefineBitsLossless*)
├── sounds/                <id>_<export>.wav.mp3 …     (DefineSound + streamed audio)
├── fonts/                 <id>_<name>.ttf             (DefineFont2/3)
├── fonts_woff/            <id>_<name>.woff
├── font4/                 (empty: this SWF has no DefineFont4)
├── texts/                 <id>.txt                    (DefineText, DefineEditText)
├── buttons/               <id>.png                    (DefineButton2 states)
├── symbolClass/           symbols.csv                  (ExportAssets / SymbolClass)
├── binaryData/            (empty: no DefineBinaryData tags)
├── frames/                <n>.png                     main timeline, n = 1..22
├── xfl/                   XFL project (DOMDocument.xml + LIBRARY/ + bin/)
└── sprites/               DefineSprite_<id>[_name]/<frame>.svg   (opt-in stage)
```

## 2. Naming rules actually observed

FFDec uses the original numeric id in every name. It appends the export name
when the symbol has one.

| kind | pattern | example |
| --- | --- | --- |
| shape | `<id>.svg` | `shapes/233.svg` |
| morph shape | `<id>.svg` | `morphshapes/530.svg` |
| image | `<id>.<ext>` | `images/234.jpg`, `images/780.png` |
| sound | `<id>_<exportName>.<origExt>.mp3` | `sounds/1_sfx_14.mp3.mp3` |
| font | `<id>_<fontName>.ttf` | `fonts/263_Arial Black.woff` |
| text | `<id>.txt` | `texts/1002.txt` |
| button | `<id>.png` | `buttons/1313.png` |
| sprite frames | `DefineSprite_<id>[_<name>]/<frame>.svg` | `sprites/DefineSprite_7858_petMC06/1.svg` |
| XFL symbol | `LIBRARY/Symbol <id>.xml` | `LIBRARY/Symbol 237.xml` |
| XFL bitmap | `LIBRARY/Bitmap <id>.png` | `LIBRARY/Bitmap 102.png` |
| XFL sound | `LIBRARY/sound<id>.wav` | `LIBRARY/sound5300.wav` |
| script | scope path + `DoAction.as` / `CLIPACTIONRECORD ….as` | `scripts/as/DefineSprite_237/frame_2/DoAction.as` |

**Ids are never renumbered.** `manifests/characters.json` is keyed by the SWF's
own character ids, and every extracted file name repeats that id so the mapping
survives even without the manifest.

## 3. Manifests

| file | contents |
| --- | --- |
| `swf_header.json` | signature, version, compression, declared vs actual length, stage rect in twips and px, frame rate raw + fps, main frame count, background, metadata XML, main-timeline frame labels |
| `tags.json` | every tag in file order: `offset`, `code`, `name`, `length`, `depth`, `timeline` (0 = main), `timeline_type`, `frame`, `parent_sprite`, plus per-tag extras (`character_id`, `place_depth`, `child_character_id`, `export_assets`, `frame_label`, `avm1_*_count`, `sound_character_id`, …) |
| `characters.json` | one entry per character id: `definitions[]`, `kinds[]`, `export_names[]`, `frame_labels[]`, `declared_frame_count`, `counted_showframe_tags`, `child_ids[]`, `sound{}`, `image{}`, `font{}` |
| `relationships.json` | `PlaceObject2/3` edges: `timeline`, `frame`, `child_character_id`, `depth`, `offset` |
| `as2_strings.json` | every AVM1 string literal with `kind` (`constant_pool` / `push`), `value`, `location`, `offset` |
| `as2_strings.txt` | the same literals as a frequency-sorted text index (tracked; the JSON is git-ignored for size) |
| `export_manifest.json` | every extracted file: `path`, `kind`, `character_id`, `frame`, `timeline_character_id`, `bytes`, `sha256`, `character` (ids, export names, frame labels), `parse_note` |
| `export_manifest.csv` | flat index of the above |
| `coverage.json` | expected vs extracted character counts per kind, plus unresolved ids |
| `verification.json` | all verification checks and their results |
| `summary.json` | one-screen overview used by the report generator |

`character_id: 0` in the manifest means "main timeline" (the `frames/` PNGs).

## 4. Tracing a file back to the SWF

Example: `extracted/sprites/DefineSprite_237/1.svg`.

1. `manifests/characters.json` → `"237"` → `definitions[0]` =
   `DefineSprite`, `offset 225725`, `length 820`, declared 15 frames,
   `child_ids [1,2,3]`.
2. `manifests/tags.json` → filter `offset >= 225725 && offset < 226545` to get the
   sprite body, including its `DoAction`, `PlaceObject2` and `ShowFrame` tags.
3. `manifests/export_manifest.json` → the file's `sha256` and size, so you can
   prove the file on disk is the one that was extracted.
4. `extracted/xfl/LIBRARY/Symbol 237.xml` (if present) → the same sprite as an
   editable XFL timeline.

Every manifest records `source_swf_sha256`, so a manifest can never be silently
applied to a different build.

## 5. Decompiler quirks the pipeline works around

These are all reproducible; they are why the pipeline does what it does.

1. **FFDec writes into the output root if that directory is not empty.** Given a
   populated `-export` directory it dumps `<id>.svg`, `<id>.png` … straight into
   it instead of creating `shapes/`, `images/`. The pipeline therefore exports
   into a fresh `.scratch_<stage>/` directory and publishes afterwards.
2. **`-select` is ignored for sprite export in this build.** `-select 237:1`
   still renders all 1,945 sprites / 23,998 frames. The sprite stage is therefore
   opt-in and always complete (measured: 6–9 min, ~1.6 GB).
3. **Sprite export writes the whole tree twice.** FFDec emits each sprite under
   `sprites/` *and* as a sibling `DefineSprite_<id>` directory at the output root
   (observed: 1,897 duplicate directories, byte-identical, ~1.6 GB). The pipeline
   detects a sibling whose name already exists in the published directory and
   discards it, logging one `note:` line per duplicate. Anything that is *not* a
   known duplicate is quarantined under `extracted/_unexpected/` instead of being
   silently dropped.
4. **`-format font:ttf,font:woff` only emits one format.** Splitting into
   `fonts_ttf`, `fonts_woff` and `font4` stages is required to get both.
5. **Sound files get a duplicated extension** (`1_sfx_14.mp3.mp3`,
   `7880_BTNout.wav.mp3`). The inner extension is the real container. Names are
   kept verbatim so the manifest stays a faithful record of the decompiler's
   output. `sounds/-1.wav` is the streamed (non-`DefineSound`) audio.
6. **XFL is not a complete symbol dump.** See §6.
7. **`texts/` holds text content, not layout.** `DefineEditText` appearance
   depends on the runtime font, so only the string is exported.
8. **`frame` in `tags.json` means "frame being built".** Tags that follow the
   final `ShowFrame` (only the closing `End` tag here) are reported as frame 23.
9. **Two independent tag parsers are kept on purpose.** `swf_inspect.py` parses
   the binary; `analysis/ffdec_dumpSWF.txt` is FFDec's listing. They agree on all
   tag counts except `End` inside sprite bodies, which FFDec omits — recorded as
   a benign difference in `verification.json`.

## 6. Known limitation: XFL symbol coverage

Measured on this SWF (`verification.json` → `checks.xfl`):

| metric | value |
| --- | --- |
| sprites defined in the SWF | 1,945 |
| sprites placed somewhere in the SWF's own timelines | 1,869 |
| sprites reachable from the main timeline | 1,867 |
| sprite symbols in `xfl/LIBRARY/` | **222** |
| sprites missing from the XFL project | 1,723 |
| of those, carrying an `ExportAssets` linkage name | 919 |

The selection is **not** explained by timeline reachability (1,867 sprites are
reachable) nor by linkage (919 exported sprites are missing), so this is a
limitation of FFDec's XFL exporter rather than a property of the file. Treat
`extracted/xfl/` as the authored-screen source (22 main frames + the symbols it
did export) and use:

- `extracted/sprites/` (opt-in) for every sprite frame, 23,998 files, all 1,945
  sprites including the player rig and all weapon animations;
- `extracted/scripts/as/` for the code of every sprite, exported or not.

Concretely: `characterMC` (id 3268, attached at runtime by
`frame_1/DoAction.as:3861`) has **no** `Symbol 3268.xml`, and neither do its
children `gfoKHPq` (2530), `fqBEfG` (1767) or any attack animation sprite. The
player rig is therefore documented from the sprite SVGs and the ActionScript, not
from XFL.

## 7. Reproducibility notes

- `scripts/*.py` are standard library only; no pip installs.
- The decompiler version is pinned in `manifests/ffdec_version.txt` and printed
  in the report. A different FFDec build may change file naming or formatting.
- JSON/CSV manifests are deterministic for a given SWF and FFDec build.
- XFL files embed `lastModified` timestamps and generated item ids, so the XFL
  tree is **not** byte-identical between runs. The hash check in
  `verify_extraction.py` always compares against the manifest produced by the
  same run, so it remains meaningful; do not compare XFL hashes across runs.
- `extracted/` and `logs/` are git-ignored. The manifests, analysis and docs are
  the reviewable record; regenerate the assets with one command.
