#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# extract_sab558.sh -- reproducible extraction pipeline for Stick Arena
#                     Ballistick 558 (htdocs/stickarena/sab558.swf)
#
# Design rules
#   * The original SWF is opened read-only; its SHA-256 is verified before and
#     after every run. Nothing under htdocs/ or ballistickemu/ is ever written.
#   * Every stage is a separate decompiler invocation so a failure in one asset
#     class cannot poison the others. Each stage records exit code + duration in
#     logs/stages.jsonl.
#   * Stages are idempotent: existing output is reused unless --force is given.
#   * All generated output lands under reference/sab558/extracted/.
#
# Usage
#   ./extract_sab558.sh [options]
#     --force                 re-run stages even if their output exists
#     --only a,b,c            run only the named stages
#     --skip a,b,c            skip the named stages
#     --with-sprite-frames    also render every sprite frame to SVG
#                             (measured: 23,984 files / ~1.6 GB / ~6 min)
#     --with-swf-xml          also write FFDec's full SWF->XML dump (~65 MB)
#     --verify-only           rebuild manifests + verification from existing output
#     --list                  list stage names
#     -h | --help             this text
#
# Environment
#   FFDEC   path to ffdec-cli executable (default: auto-detect)
#   PYTHON  python interpreter (default: python)
#   SAB558_SWF  override input SWF path
# ---------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"          # reference/sab558
REPO_ROOT="$(cd "$REF_DIR/../.." && pwd)"        # repository root
SWF="${SAB558_SWF:-$REPO_ROOT/htdocs/stickarena/sab558.swf}"
OUT="$REF_DIR/extracted"
MAN="$REF_DIR/manifests"
LOG="$REF_DIR/logs"
ANALYSIS="$REF_DIR/analysis"
PYTHON="${PYTHON:-python}"

mkdir -p "$OUT" "$MAN" "$LOG" "$ANALYSIS"

# ---------------------------------------------------------------- ffdec ----
find_ffdec() {
  if [[ -n "${FFDEC:-}" ]]; then printf '%s' "$FFDEC"; return 0; fi
  local c
  for c in ffdec-cli ffdec-cli.exe \
           "/c/Program Files (x86)/FFDec/ffdec-cli.exe" \
           "/c/Program Files/FFDec/ffdec-cli.exe" \
           "/opt/ffdec/ffdec.sh" "/usr/local/bin/ffdec"; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
    if [[ -x "$c" ]]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}
FFDEC_BIN="$(find_ffdec)" || {
  echo "ERROR: ffdec-cli not found. Set FFDEC=/path/to/ffdec-cli(.exe)." >&2
  exit 1
}

STAGE_ORDER="inspect tags_dump scripts_as scripts_pcode shapes morphshapes images
sounds fonts_ttf fonts_woff font4 text binary symbolclass buttons frames xfl"

list_stages() {
  echo "stages (in order):"
  for s in $STAGE_ORDER; do echo "  $s"; done
  echo "  sprite_frames   (opt-in, --with-sprite-frames)"
  echo "  swf_xml         (opt-in, --with-swf-xml)"
  echo
  echo "manifests are always rebuilt afterwards (link_exports.py + verify_extraction.py)"
}

# ------------------------------------------------------------- arguments ---
FORCE=0
ONLY=""
SKIP=""
WITH_SPRITE_FRAMES=0
WITH_SWF_XML=0
VERIFY_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --skip) SKIP="${2:-}"; shift 2 ;;
    --with-sprite-frames) WITH_SPRITE_FRAMES=1; shift ;;
    --with-swf-xml) WITH_SWF_XML=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --list) list_stages; exit 0 ;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

in_list() {  # in_list needle "a,b,c"
  local needle="$1" hay="$2"
  [[ -z "$hay" ]] && return 1
  [[ ",$hay," == *",$needle,"* ]]
}

selected() {
  local s="$1"
  if [[ -n "$ONLY" ]] && ! in_list "$s" "$ONLY"; then return 1; fi
  if in_list "$s" "$SKIP"; then return 1; fi
  return 0
}

record_stage() {  # name status seconds detail
  "$PYTHON" - "$LOG/stages.jsonl" "$1" "$2" "$3" "$4" <<'PY'
import datetime, json, sys
path, name, status, secs, detail = sys.argv[1:6]
rec = {"stage": name, "status": status, "seconds": float(secs), "detail": detail,
       "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec) + "\n")
PY
}

FAILED=""
run_stage() {  # name marker_path fn
  local name="$1" marker="$2" fn="$3"
  if ! selected "$name"; then echo "  [skip] $name"; return 0; fi
  if [[ $FORCE -eq 0 && -e "$marker" ]]; then
    echo "  [reuse] $name"
    return 0
  fi
  local logf="$LOG/stage_${name}.log" t0 t1 rc
  echo "  [run] $name"
  t0=$(date +%s)
  "$fn" >"$logf" 2>&1
  rc=$?
  t1=$(date +%s)
  if [[ $rc -ne 0 ]]; then
    echo "    FAILED (exit $rc) -- see logs/stage_${name}.log" >&2
    record_stage "$name" failed "$((t1 - t0))" "exit=$rc"
    FAILED="$FAILED $name"
    return $rc
  fi
  record_stage "$name" ok "$((t1 - t0))" "log=stage_${name}.log"
  echo "    ok ($((t1 - t0))s)"
}

ffdec() { "$FFDEC_BIN" "$@"; }

sha_of() {
  "$PYTHON" - "$1" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}

# ----------------------------------------------------------- stage impls ---
# Every decompiler call gets a fresh, empty scratch directory. Reason: FFDec
# writes into <outdir>/<type>/ only when <outdir> is empty; if <outdir> already
# holds files it dumps everything straight into <outdir>. Isolating each call in
# its own scratch dir makes the layout deterministic, and publishing afterwards
# keeps a failure from half-writing the final tree.
stage_inspect()   { "$PYTHON" "$SCRIPT_DIR/swf_inspect.py" "$SWF" "$MAN"; }
stage_tags_dump() { ffdec -dumpSWF "$SWF" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' > "$ANALYSIS/ffdec_dumpSWF.txt"; }

# FFDec's own subdirectory name for each exported item type.
declare -A FFDEC_SUBDIR=(
  [shapes]=shapes
  [morphshapes]=morphshapes
  [images]=images
  [sounds]=sounds
  [fonts_ttf]=fonts
  [fonts_woff]=fonts
  [font4]=font4
  [text]=texts
  [buttons]=buttons
  [frames]=frames
  [binary]=binaryData
  [symbolclass]=symbolClass
  [scripts_as]=scripts
  [scripts_pcode]=scripts
  [xfl]=sab558
  [sprite_frames]=sprites
)

# publish <stage> <scratch> <final-dir>
publish() {
  local stage="$1" scratch="$2" final="$3" src
  src="$scratch/${FFDEC_SUBDIR[$stage]}"
  if [[ ! -d "$src" ]]; then
    # FFDec wrote straight into the scratch dir; accept that shape too.
    src="$scratch"
  fi
  mkdir -p "$final"
  shopt -s dotglob nullglob
  local items=("$src"/*)
  if [[ ${#items[@]} -eq 0 ]]; then
    shopt -u dotglob nullglob
    # Legitimate empty result: the SWF defines no character of this kind.
    # The coverage check in verify_extraction.py is what catches real gaps.
    echo "note: stage $stage produced no files (no such character kind in the SWF)"
    rm -rf "$scratch"
    return 0
  fi
  mv "${items[@]}" "$final"/
  shopt -u dotglob nullglob
  # FFDec duplicates the whole sprite tree at the output root next to the
  # sprites/ directory (observed: 1,897 identical copies, ~1.6 GB). A sibling
  # that already exists under the final directory is a byte-identical duplicate:
  # discard it. Anything genuinely unexpected is quarantined instead, so it is
  # visible but never mixed into the published tree.
  shopt -s dotglob nullglob
  for d in "$scratch"/*; do
    [[ -d "$d" ]] || continue
    [[ "$d" == "$src" ]] && continue
    local base
    base="$(basename "$d")"
    if [[ -d "$final/$base" ]]; then
      rm -rf "$d"
      echo "note: discarded duplicate sibling output from stage $stage: $base"
    else
      mkdir -p "$OUT/_unexpected/$stage"
      mv "$d" "$OUT/_unexpected/$stage/" 2>/dev/null || true
      echo "note: quarantined unexpected sibling output from stage $stage: $base"
    fi
  done
  shopt -u dotglob nullglob
  rm -rf "$scratch"
  return 0
}

# export_stage <stage> <final-dir> -- <ffdec args...>
export_stage() {
  local stage="$1" final="$2"; shift 2
  [[ "${1:-}" == "--" ]] && shift
  local scratch="$OUT/.scratch_$stage"
  rm -rf "$scratch"; mkdir -p "$scratch"
  ffdec "$@" "$scratch" "$SWF" || { rm -rf "$scratch"; return 1; }
  publish "$stage" "$scratch" "$final"
}

stage_scripts_as()    { export_stage scripts_as    "$OUT/scripts/as"    -- -format script:as -export script; }
stage_scripts_pcode() { export_stage scripts_pcode "$OUT/scripts/pcode" -- -format script:pcode -export script; }
stage_shapes()        { export_stage shapes        "$OUT/shapes"        -- -format shape:svg -export shape; }
stage_morphshapes()   { export_stage morphshapes   "$OUT/morphshapes"   -- -format morphshape:svg -export morphshape; }
stage_images()        { export_stage images        "$OUT/images"        -- -format image:png_gif_jpeg -export image; }
stage_sounds()        { export_stage sounds        "$OUT/sounds"        -- -format sound:mp3_wav -export sound; }
stage_fonts_ttf()   { export_stage fonts_ttf     "$OUT/fonts"      -- -format font:ttf -export font; }
stage_fonts_woff()  { export_stage fonts_woff    "$OUT/fonts_woff" -- -format font:woff -export font; }
stage_font4()       { export_stage font4         "$OUT/font4"      -- -format font4:cff -export font4; }
stage_text()          { export_stage text          "$OUT/texts"         -- -format text:plain -export text; }
stage_binary()        { export_stage binary        "$OUT/binaryData"    -- -export binaryData; }
stage_symbolclass()   { export_stage symbolclass   "$OUT/symbolClass"   -- -export symbolClass; }
stage_buttons()       { export_stage buttons       "$OUT/buttons"       -- -format button:png -export button; }
stage_frames()        { export_stage frames        "$OUT/frames"        -- -format frame:png -export frame; }
stage_xfl()           { export_stage xfl           "$OUT/xfl"           -- -format xfl:cs6 -export xfl; }
stage_sprite_frames() { export_stage sprite_frames "$OUT/sprites"       -- -format sprite:svg -export sprite; }
stage_swf_xml()       { mkdir -p "$OUT/swf_xml" && ffdec -swf2xml "$SWF" "$OUT/swf_xml/sab558.xml"; }

marker_for() {
  case "$1" in
    inspect) echo "$MAN/summary.json" ;;
    tags_dump) echo "$ANALYSIS/ffdec_dumpSWF.txt" ;;
    scripts_as) echo "$OUT/scripts/as/.stage_ok" ;;
    scripts_pcode) echo "$OUT/scripts/pcode/.stage_ok" ;;
    shapes) echo "$OUT/shapes/.stage_ok" ;;
    morphshapes) echo "$OUT/morphshapes/.stage_ok" ;;
    images) echo "$OUT/images/.stage_ok" ;;
    sounds) echo "$OUT/sounds/.stage_ok" ;;
    fonts_ttf) echo "$OUT/fonts/.stage_ok" ;;
    fonts_woff) echo "$OUT/fonts_woff/.stage_ok" ;;
    font4) echo "$OUT/font4/.stage_ok" ;;
    text) echo "$OUT/texts/.stage_ok" ;;
    binary) echo "$OUT/binaryData/.stage_ok" ;;
    symbolclass) echo "$OUT/symbolClass/.stage_ok" ;;
    buttons) echo "$OUT/buttons/.stage_ok" ;;
    frames) echo "$OUT/frames/.stage_ok" ;;
    xfl) echo "$OUT/xfl/.stage_ok" ;;
    sprite_frames) echo "$OUT/sprites/.stage_ok" ;;
    swf_xml) echo "$OUT/swf_xml/sab558.xml" ;;
    *) echo "" ;;
  esac
}

# ------------------------------------------------------------- preflight ---
echo "== sab558 extraction pipeline =="
echo "repo    : $REPO_ROOT"
echo "swf     : $SWF"
echo "ffdec   : $FFDEC_BIN"
echo "python  : $($PYTHON --version 2>&1)"
echo

if [[ ! -f "$SWF" ]]; then
  echo "ERROR: input SWF not found: $SWF" >&2
  exit 1
fi

SWF_SHA="$(sha_of "$SWF")"
SWF_BYTES="$(wc -c < "$SWF" | tr -d ' ')"
echo "sha256  : $SWF_SHA"
echo "bytes   : $SWF_BYTES"
echo
mkdir -p "$REF_DIR/source"
printf '%s  sab558.swf\n' "$SWF_SHA" > "$REF_DIR/source/SHA256SUMS"
{
  echo "original_path: htdocs/stickarena/sab558.swf"
  echo "sha256: $SWF_SHA"
  echo "bytes: $SWF_BYTES"
  echo "captured_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "note: the original file is never copied over or modified; this is its identity record."
} > "$REF_DIR/source/SOURCE.txt"
{
  "$FFDEC_BIN" -help 2>&1 | head -3 | sed 's/\x1b\[[0-9;]*m//g'
  java -version 2>&1 | head -2
} > "$MAN/ffdec_version.txt"

if [[ $VERIFY_ONLY -eq 1 ]]; then
  echo "-- verify-only --"
  "$PYTHON" "$SCRIPT_DIR/link_exports.py" "$REF_DIR" || exit 1
  "$PYTHON" "$SCRIPT_DIR/verify_extraction.py" "$REF_DIR" || exit 1
  exit 0
fi

# ---------------------------------------------------------------- stages ---
echo "== stages =="
for s in $STAGE_ORDER; do
  run_stage "$s" "$(marker_for "$s")" "stage_$s"
done

if [[ $WITH_SPRITE_FRAMES -eq 1 ]]; then
  run_stage sprite_frames "$(marker_for sprite_frames)" stage_sprite_frames
else
  echo "  [skip] sprite_frames (opt-in --with-sprite-frames; measured 23,984 files / ~1.6 GB)"
fi

if [[ $WITH_SWF_XML -eq 1 ]]; then
  run_stage swf_xml "$(marker_for swf_xml)" stage_swf_xml
else
  echo "  [skip] swf_xml (opt-in --with-swf-xml; ~65 MB full SWF->XML dump)"
fi

# ------------------------------------------------------------- manifests ---
echo
echo "== manifests =="
"$PYTHON" "$SCRIPT_DIR/link_exports.py" "$REF_DIR" || { echo "linker failed" >&2; exit 1; }
"$PYTHON" "$SCRIPT_DIR/verify_extraction.py" "$REF_DIR" || { echo "verification failed" >&2; exit 1; }

# ------------------------------------------------------------- integrity ---
AFTER_SHA="$(sha_of "$SWF")"
if [[ "$AFTER_SHA" != "$SWF_SHA" ]]; then
  echo "FATAL: original SWF changed during extraction ($SWF_SHA -> $AFTER_SHA)" >&2
  exit 1
fi
echo
echo "original SWF unchanged (sha256 $AFTER_SHA)"
if [[ -n "$FAILED" ]]; then
  echo "WARNING: failed stages:$FAILED" >&2
  exit 3
fi
echo "done. See analysis/extraction_report.md"
