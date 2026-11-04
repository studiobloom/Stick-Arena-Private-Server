# Toolchain: JPEXS Free Flash Decompiler

## 1. What is installed

| property | value |
| --- | --- |
| product | JPEXS Free Flash Decompiler |
| version | `v.26.4.0 nightly build 3604` |
| install path | `C:\Program Files (x86)\FFDec` |
| CLI binary | `C:\Program Files (x86)\FFDec\ffdec-cli.exe` |
| library jar | `C:\Program Files (x86)\FFDec\ffdec.jar` |
| launcher script | `ffdec.bat` (GUI), `ffdec-cli.exe` (CLI) |
| Java runtime | `java version "1.8.0_491"` (Oracle JRE 8, x64) |
| user config | `%APPDATA%\JPEXS\FFDec\config.toml` (+ legacy `config.bin`) |
| licence | `C:\Program Files (x86)\FFDec\license.txt` |

The pipeline auto-detects the binary in this order: `$FFDEC`, `ffdec-cli` on
`PATH`, the two Program Files locations above, `/opt/ffdec/ffdec.sh`. Nothing is
installed or modified by the pipeline.

Recorded per run in `manifests/ffdec_version.txt`.

## 2. CLI surface (verified against `-help`)

Top-level commands present in this build:

```
-export            export sources (the only command the pipeline uses for assets)
-dumpSWF           list SWF tags to stdout
-dumpAS2           list AS1/AS2 scripts
-dumpAS3           list AS3 scripts
-swf2xml           convert SWF to XML (lossless, re-importable)
-xml2swf           convert XML back to SWF
-decompress        -compress      SWF container compression
-deobfuscate       AS3 P-code deobfuscation
-extract           pull SWFs out of ZIP/other containers
-linkReport        linker report
-swf2swc           SWC generation
-replace / -remove / -import*     tag-level editing (NOT used here)
```

`-export` item types: `script image shape morphshape movie font font4 frame
sprite button sound binaryData symbolClass text all fla xfl mxml flashdevelop
intellij vscode`. Output format is chosen with the `-format` pre-option, e.g.
`script:as`, `script:pcode`, `shape:svg`, `image:png_gif_jpeg`, `sound:mp3_wav`,
`font:ttf`, `font:woff`, `frame:png`, `button:png`, `xfl:cs6`.

## 3. What the pipeline actually calls

| stage | command |
| --- | --- |
| scripts_as | `-format script:as -export script <out> <swf>` |
| scripts_pcode | `-format script:pcode -export script <out> <swf>` |
| shapes | `-format shape:svg -export shape <out> <swf>` |
| morphshapes | `-format morphshape:svg -export morphshape <out> <swf>` |
| images | `-format image:png_gif_jpeg -export image <out> <swf>` |
| sounds | `-format sound:mp3_wav -export sound <out> <swf>` |
| fonts_ttf / fonts_woff / font4 | `-format font:ttf` / `font:woff` / `font4:cff` with `-export font` / `font4` |
| text | `-format text:plain -export text <out> <swf>` |
| binary | `-export binaryData <out> <swf>` |
| symbolclass | `-export symbolClass <out> <swf>` |
| buttons | `-format button:png -export button <out> <swf>` |
| frames | `-format frame:png -export frame <out> <swf>` |
| xfl | `-format xfl:cs6 -export xfl <out> <swf>` |
| sprite_frames | `-format sprite:svg -export sprite <out> <swf>` |
| swf_xml | `-swf2xml <swf> <out>/sab558.xml` |
| tags_dump | `-dumpSWF <swf>` |

`-swf2xml` is also used as an independent cross-check of the header: FFDec reports
`version="8" frameCount="22" frameRate="34.0" compression="NONE"` and
`displayRect Xmax="11000" Ymax="8000"`, matching `manifests/swf_header.json`.

## 4. Verified CLI limitations of this build

These were measured on `sab558.swf`, not assumed:

| limitation | evidence | workaround in the pipeline |
| --- | --- | --- |
| `-select` is ignored for sprite export | `-select 237:1` still produced 23,984 frames in 1,945 directories | sprite stage is all-or-nothing and opt-in |
| only one format per item type is honoured | `-format font:ttf,font:woff` produced WOFF files only | separate `fonts_ttf` / `fonts_woff` / `font4` stages |
| output layout depends on the output directory's state | exporting into a non-empty directory writes `<id>.svg` etc. into it instead of `shapes/` | every call gets a fresh `.scratch_<stage>/` |
| sprite export duplicates the tree | each sprite appears under `sprites/` and again as a root-level `DefineSprite_<id>` (1,897 dirs, byte-identical) | duplicates detected by name and discarded, logged |
| XFL export is not exhaustive | 222 of 1,945 sprites appear as `LIBRARY/Symbol <id>.xml` | documented; `sprites/` covers the rest |
| sound filenames keep the original extension | `1_sfx_14.mp3.mp3`, `7880_BTNout.wav.mp3` | names preserved verbatim, manifest records the real path |
| `-dumpSWF` omits the `End` tag inside `DefineSprite` bodies | 75,446 vs 77,391 tags, difference is exactly the sprite `End` tags | cross-check compares by tag code and treats code 0 as benign |

## 5. Decompiler independence

The structural manifests (`swf_header.json`, `tags.json`, `characters.json`,
`relationships.json`, `as2_strings.json`) are produced by
`scripts/swf_inspect.py`, a standalone Python parser, **not** by FFDec. That
means the repository can still describe the SWF's structure and identifiers if
the decompiler is upgraded, removed or behaves differently.

The two parsers are compared on every verification run
(`verification.json` → `checks.parser_cross_check`).
