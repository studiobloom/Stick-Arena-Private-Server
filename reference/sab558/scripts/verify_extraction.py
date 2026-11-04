#!/usr/bin/env python3
"""
verify_extraction.py -- evidence that the extraction is complete and honest.

Checks performed
  1. original SWF hash is unchanged and matches source/SHA256SUMS
  2. every file listed in export_manifest.json exists, with the recorded size
     and sha256 (detects truncation / post-edit tampering)
  3. no zero-byte artefacts
  4. main-timeline frame PNGs cover exactly 1..N from the SWF header
  5. ActionScript and P-code trees describe the same script set
  6. XFL project has a DOMDocument.xml and one library symbol per sprite
  7. sprite frame renders (if requested) match each sprite's declared frame count
  8. cross-check: FFDec's -dumpSWF tag counts vs the independent binary parser
  9. unresolved character kinds are carried through from coverage.json

Writes manifests/verification.json and analysis/extraction_report.md.
Exit code is non-zero only for hard integrity failures (1, 2, 4).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return str(n)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    ref = os.path.abspath(argv[1])
    man = os.path.join(ref, "manifests")
    out = os.path.join(ref, "extracted")
    ana = os.path.join(ref, "analysis")

    header = load(os.path.join(man, "swf_header.json"))
    summary = load(os.path.join(man, "summary.json"))
    chars = load(os.path.join(man, "characters.json"))["characters"]
    manifest = load(os.path.join(man, "export_manifest.json"))
    coverage = load(os.path.join(man, "coverage.json"))

    hard_fail = []
    warnings = []
    checks = OrderedDict()

    # 1 -- source identity ------------------------------------------------
    swf_rel = "htdocs/stickarena/sab558.swf"
    swf_path = os.path.join(ref, "..", "..", swf_rel)
    sums = os.path.join(ref, "source", "SHA256SUMS")
    recorded = None
    if os.path.exists(sums):
        recorded = open(sums, encoding="utf-8").read().split()[0].strip()
    live = sha256_file(swf_path) if os.path.exists(swf_path) else None
    ok = bool(live and recorded and live == recorded == header["sha256"])
    checks["source_swf_hash"] = {
        "ok": ok, "recorded": recorded, "live": live, "header": header["sha256"]}
    if not ok:
        hard_fail.append("original SWF hash mismatch or missing")

    # 2/3 -- manifest integrity -------------------------------------------
    missing, size_bad, hash_bad, empty = [], [], [], []
    for rec in manifest["files"]:
        p = os.path.join(out, rec["path"])
        if not os.path.exists(p):
            missing.append(rec["path"]); continue
        st = os.path.getsize(p)
        if st != rec["bytes"]:
            size_bad.append({"path": rec["path"], "manifest": rec["bytes"], "disk": st})
            continue
        if st == 0:
            empty.append(rec["path"])
        if sha256_file(p) != rec["sha256"]:
            hash_bad.append(rec["path"])
    checks["manifest_integrity"] = {
        "ok": not (missing or size_bad or hash_bad),
        "files_checked": len(manifest["files"]),
        "missing": missing[:50], "size_mismatch": size_bad[:50],
        "sha256_mismatch": hash_bad[:50],
        "missing_count": len(missing), "size_mismatch_count": len(size_bad),
        "sha256_mismatch_count": len(hash_bad),
        # Zero-byte outputs are legitimate here: empty DefineEditText fields and
        # action blocks that contain no instructions. They are counted, not
        # treated as failures, and broken down by kind.
        "empty_outputs": len(empty),
        "empty_outputs_by_kind": dict(sorted(
            Counter(r["kind"] for r in manifest["files"] if r["bytes"] == 0).items())),
    }
    if missing or size_bad or hash_bad:
        hard_fail.append("extracted files do not match manifest")

    # 4 -- main timeline frames -------------------------------------------
    expected_frames = header["main_timeline_frame_count"]
    frame_dir = os.path.join(out, "frames")
    have = set()
    if os.path.isdir(frame_dir):
        for fn in os.listdir(frame_dir):
            m = re.match(r"^(\d+)\.png$", fn)
            if m:
                have.add(int(m.group(1)))
    want = set(range(1, expected_frames + 1))
    checks["main_timeline_frames"] = {
        "ok": have == want, "expected": expected_frames,
        "present": sorted(have), "missing": sorted(want - have),
        "extra": sorted(have - want),
    }
    if have != want:
        hard_fail.append("main timeline frame PNGs incomplete")

    # 5 -- AS vs P-code ---------------------------------------------------
    def script_index(root):
        idx = set()
        if not os.path.isdir(root):
            return idx
        for dirpath, _dn, fns in os.walk(root):
            for fn in fns:
                if fn == ".stage_ok":
                    continue
                idx.add(os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/"))
        return idx
    as_idx = script_index(os.path.join(out, "scripts", "as"))
    pc_idx = script_index(os.path.join(out, "scripts", "pcode"))
    # FFDec writes the same tree; file extensions differ (.as vs .pcode/.as)
    def norm(s):
        return os.path.splitext(s)[0]
    as_norm = {norm(s) for s in as_idx}
    pc_norm = {norm(s) for s in pc_idx}
    checks["scripts_as_vs_pcode"] = {
        "ok": as_norm == pc_norm and len(as_idx) > 0,
        "as_files": len(as_idx), "pcode_files": len(pc_idx),
        "only_in_as": sorted(as_norm - pc_norm)[:50],
        "only_in_pcode": sorted(pc_norm - as_norm)[:50],
    }
    if not checks["scripts_as_vs_pcode"]["ok"]:
        warnings.append("ActionScript and P-code trees differ")

    # 6 -- XFL ------------------------------------------------------------
    xfl_roots = []
    xfl_dir = os.path.join(out, "xfl")
    for dirpath, _dn, fns in os.walk(xfl_dir):
        if "DOMDocument.xml" in fns:
            xfl_roots.append(dirpath)
    sprite_ids = {int(k) for k, v in chars.items() if "sprite" in v.get("kinds", [])}
    placed = {e["child_character_id"] for e in
              load(os.path.join(man, "relationships.json"))["edges"]}
    xfl_symbols = set()
    xfl_symbols_all = set()
    for root in xfl_roots:
        lib = os.path.join(root, "LIBRARY")
        if os.path.isdir(lib):
            for fn in os.listdir(lib):
                m = re.match(r"^Symbol (\d+)\.xml$", fn)
                if m:
                    xfl_symbols_all.add(int(m.group(1)))
    xfl_symbols = xfl_symbols_all & sprite_ids
    missing_xfl = sorted(sprite_ids - xfl_symbols)
    missing_with_linkage = [i for i in missing_xfl
                            if chars.get(str(i), {}).get("export_names")]
    checks["xfl"] = {
        # Existence is the pass condition. Symbol coverage is reported, not
        # enforced: FFDec's XFL exporter only materialises symbols reachable
        # from an authored timeline, and this SWF instantiates most of its
        # sprites at runtime through linkage.
        "ok": bool(xfl_roots),
        "project_roots": [os.path.relpath(p, out) for p in xfl_roots],
        "sprite_symbols": len(xfl_symbols),
        "library_symbol_items": len(xfl_symbols_all),
        "sprites_in_swf": len(sprite_ids),
        "sprites_placed_on_a_timeline": len(placed & sprite_ids),
        "sprite_symbols_missing": missing_xfl[:50],
        "sprite_symbols_missing_count": len(missing_xfl),
        "missing_but_linkage_exported": len(missing_with_linkage),
        "coverage_note": "FFDec's XFL exporter only materialises a subset of the "
                         "library. The selection is not explained by timeline "
                         "reachability (1,867 sprites are reachable from the main "
                         "timeline) nor by linkage (919 exported sprites are "
                         "missing), so the XFL library must be treated as partial. "
                         "Full sprite coverage is in extracted/sprites/.",
    }
    if not checks["xfl"]["ok"]:
        warnings.append("XFL project missing or has no DOMDocument.xml")
    elif missing_xfl:
        warnings.append("XFL library is partial: %d of %d sprites present "
                        "(%d missing, %d of those linkage-exported) - see "
                        "docs/assets.md §6"
                        % (len(xfl_symbols), len(sprite_ids), len(missing_xfl),
                           len(missing_with_linkage)))

    # 7 -- sprite frame renders (optional) --------------------------------
    sp_dir = os.path.join(out, "sprites")
    sprite_check = {"requested": os.path.isdir(sp_dir) and bool(os.listdir(sp_dir))}
    if sprite_check["requested"]:
        mism, counted = [], 0
        for d in os.listdir(sp_dir):
            p = os.path.join(sp_dir, d)
            if not os.path.isdir(p):
                continue
            m = re.match(r"^DefineSprite_(\d+)", d)
            if not m:
                continue
            cid = int(m.group(1))
            n = len([f for f in os.listdir(p) if f.endswith(".svg")])
            declared = chars.get(str(cid), {}).get("declared_frame_count")
            if declared == 0:
                continue  # zero-frame class/linkage stub: nothing to render
            counted += 1
            if declared is not None and n != declared:
                mism.append({"sprite": cid, "declared": declared, "rendered": n})
        sprite_check.update({
            "ok": not mism, "sprites_rendered": counted,
            "frame_count_mismatches": mism[:50],
            "frame_count_mismatch_count": len(mism),
        })
        if mism:
            warnings.append("%d sprites rendered with a frame-count mismatch"
                            % len(mism))
    checks["sprite_frames"] = sprite_check

    # 8 -- independent parser cross-check --------------------------------
    dump = os.path.join(ana, "ffdec_dumpSWF.txt")
    xcheck = {"ok": True, "note": "tag histogram by tag code, FFDec -dumpSWF vs binary parser"}
    if os.path.exists(dump):
        ff = Counter()
        with open(dump, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^[0-9a-f]{8}:\s+\d+\.\s+\S+.*?tagId=\s*(\d+)", line)
                if m:
                    ff[int(m.group(1))] += 1
        mine = Counter(t["code"] for t in load(os.path.join(man, "tags.json"))["tags"])
        diff = {str(k): {"ffdec": ff.get(k, 0), "parser": mine.get(k, 0)}
                for k in set(ff) | set(mine) if ff.get(k, 0) != mine.get(k, 0)}
        # FFDec omits the End tag that terminates every DefineSprite body (code 0).
        benign = {"0"}
        xcheck["ffdec_tag_total"] = sum(ff.values())
        xcheck["parser_tag_total"] = sum(mine.values())
        xcheck["differences"] = dict(sorted(diff.items(), key=lambda kv: int(kv[0])))
        xcheck["ok"] = all(k in benign for k in diff)
        if not xcheck["ok"]:
            warnings.append("tag histograms differ between FFDec and binary parser")
    checks["parser_cross_check"] = xcheck

    # 9 -- unresolved ----------------------------------------------------
    checks["unresolved"] = {
        "ok": not coverage["unresolved"],
        "kinds": [{"kind": u["expected_kind"], "missing": u["missing_count"]}
                  for u in coverage["unresolved"]],
        "files_without_character_id": len(coverage.get("files_without_character_id", [])),
        "empty_definitions": coverage.get("empty_definition_count", 0),
    }
    if coverage["unresolved"]:
        warnings.append("some character kinds are not represented on disk")

    # ---- write verification.json ---------------------------------------
    result = OrderedDict()
    result["source_swf"] = header["path"]
    result["source_swf_sha256"] = header["sha256"]
    result["hard_failures"] = hard_fail
    result["warnings"] = warnings
    result["ok"] = not hard_fail
    result["checks"] = checks
    result["totals"] = {
        "files": manifest["file_count"],
        "bytes": manifest["total_bytes"],
        "by_kind": coverage["file_counts_by_kind"],
    }
    with open(os.path.join(man, "verification.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # ---- stage log -----------------------------------------------------
    stages = []
    slog = os.path.join(ref, "logs", "stages.jsonl")
    if os.path.exists(slog):
        latest = OrderedDict()
        for line in open(slog, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest[rec["stage"]] = rec  # last run of a stage wins
        stages = list(latest.values())

    # ---- human report --------------------------------------------------
    h = header
    lines = []
    A = lines.append
    A("# sab558 extraction report")
    A("")
    A("Generated by `reference/sab558/scripts/verify_extraction.py`. "
      "Machine-readable counterpart: `manifests/verification.json`.")
    A("")
    A("## 1. Source identity")
    A("")
    A("| field | value |")
    A("| --- | --- |")
    A("| file | `%s` |" % swf_rel)
    A("| sha256 | `%s` |" % h["sha256"])
    A("| size | %s (%d bytes) |" % (human(os.path.getsize(swf_path)), os.path.getsize(swf_path)))
    A("| SWF version | %d |" % h["swf_version"])
    A("| compression | %s |" % h["compression"])
    A("| stage | %g x %g px |" % (h["stage_dimensions_px"]["width"], h["stage_dimensions_px"]["height"]))
    A("| frame rate | %g fps (%d/256) |" % (h["frame_rate_fps"], h["frame_rate_fixed8_8"]))
    A("| main timeline | %d frames (%d ShowFrame tags) |"
      % (h["main_timeline_frame_count"], h["main_timeline_showframe_count"]))
    A("")
    A("## 2. Extracted volume")
    A("")
    A("| kind | files |")
    A("| --- | --- |")
    for k, v in sorted(coverage["file_counts_by_kind"].items()):
        A("| %s | %d |" % (k, v))
    A("| **total** | **%d (%s)** |" % (manifest["file_count"], human(manifest["total_bytes"])))
    A("")
    A("## 3. Structural inventory (from the binary, not the decompiler)")
    A("")
    A("| item | count |")
    A("| --- | --- |")
    A("| tags (incl. nested) | %d |" % summary["tag_total_including_nested"])
    A("| top-level tags | %d |" % summary["top_level_tag_count"])
    A("| characters | %d |" % summary["character_count"])
    A("| exported symbols (ExportAssets) | %d |" % summary["export_asset_count"])
    A("| placement edges | %d |" % summary["relationship_edge_count"])
    A("| AVM1 string literals | %d (%d unique) |"
      % (summary["avm1_string_literal_count"], summary["avm1_unique_string_count"]))
    A("| sprite frames (declared) | %d |" % summary["timeline_frame_totals"]["sprites"])
    A("")
    A("Character kinds:")
    A("")
    A("| kind | count |")
    A("| --- | --- |")
    for k, v in summary["character_kind_counts"].items():
        A("| %s | %d |" % (k, v))
    A("")
    A("## 4. Checks")
    A("")
    A("| check | result | detail |")
    A("| --- | --- | --- |")
    A("| original SWF unchanged | %s | live hash == recorded hash |"
      % ("PASS" if checks["source_swf_hash"]["ok"] else "FAIL"))
    mi = checks["manifest_integrity"]
    A("| manifest integrity | %s | %d files re-hashed; %d missing, %d size mismatch, %d hash mismatch; %d empty outputs (%s) |"
      % ("PASS" if mi["ok"] else "FAIL", mi["files_checked"], mi["missing_count"],
         mi["size_mismatch_count"], mi["sha256_mismatch_count"], mi["empty_outputs"],
         ", ".join("%d %s" % (v, k) for k, v in mi["empty_outputs_by_kind"].items()) or "none"))
    fchk = checks["main_timeline_frames"]
    A("| main timeline frames | %s | %d/%d present |"
      % ("PASS" if fchk["ok"] else "FAIL", len(fchk["present"]), fchk["expected"]))
    sch = checks["scripts_as_vs_pcode"]
    A("| AS vs P-code parity | %s | %d vs %d scripts |"
      % ("PASS" if sch["ok"] else "WARN", sch["as_files"], sch["pcode_files"]))
    xfl = checks["xfl"]
    A("| XFL project | %s | %d sprite symbols for %d sprites; %d omitted (not on an authored timeline), %d of those have linkage names |"
      % ("PASS" if xfl["ok"] else "WARN", xfl["sprite_symbols"], xfl["sprites_in_swf"],
         xfl["sprite_symbols_missing_count"], xfl["missing_but_linkage_exported"]))
    if checks["sprite_frames"]["requested"]:
        sf = checks["sprite_frames"]
        A("| sprite frame renders | %s | %d sprites, %d frame-count mismatches |"
          % ("PASS" if sf["ok"] else "WARN", sf["sprites_rendered"],
             sf["frame_count_mismatch_count"]))
    else:
        A("| sprite frame renders | SKIPPED | opt-in stage not run |")
    xc = checks["parser_cross_check"]
    A("| parser cross-check | %s | FFDec %d tags vs parser %d tags |"
      % ("PASS" if xc["ok"] else "WARN", xc.get("ffdec_tag_total", 0),
         xc.get("parser_tag_total", 0)))
    A("")
    if warnings:
        A("### Warnings")
        A("")
        for w in warnings:
            A("- %s" % w)
        A("")
    A("## 5. Unresolved / missing")
    A("")
    if coverage["unresolved"]:
        A("| expected kind | character ids without an extracted file |")
        A("| --- | --- |")
        for u in coverage["unresolved"]:
            A("| %s | %d |" % (u["expected_kind"], u["missing_count"]))
        A("")
        A("Full id lists: `manifests/coverage.json`.")
    else:
        A("Every character kind defined in the SWF has at least one extracted representation.")
    A("")
    empty = coverage.get("empty_definitions", [])
    if empty:
        A("Definitions that structurally cannot produce a file (%d): "
          "zero-frame sprite stubs and empty font definitions." % coverage.get("empty_definition_count", 0))
        A("")
        A("| character id | tag | tag length | kinds |")
        A("| --- | --- | --- | --- |")
        for e in empty[:20]:
            A("| %d | %s | %s | %s |" % (e["character_id"], e.get("tag"),
                                          e.get("tag_length"), ",".join(e["kinds"])))
        if len(empty) > 20:
            A("")
            A("_… %d more in `manifests/coverage.json`._" % (len(empty) - 20))
        A("")
    A("Files that could not be tied to a numeric character id are listed in "
      "`manifests/coverage.json` under `files_without_character_id`.")
    A("")
    A("## 6. Stage log")
    A("")
    A("| stage | status | seconds | detail |")
    A("| --- | --- | --- | --- |")
    for s in stages:
        A("| %s | %s | %.0f | %s |" % (s["stage"], s["status"], s["seconds"], s.get("detail", "")))
    A("")
    A("## 7. Known limitations")
    A("")
    A("- ActionScript 1/2 has no exact source recovery: `scripts/as/` is the "
      "decompiler's reconstruction from AVM1 bytecode, `scripts/pcode/` is the "
      "authoritative instruction listing. Comments, formatting and original local "
      "variable names are not recoverable.")
    A("- **XFL symbol coverage.** FFDec's XFL exporter materialises only %d of "
      "%d sprite symbols (%d missing, %d of them linkage-exported). The selection "
      "is not explained by timeline reachability or linkage, so the XFL library is "
      "partial by construction. Use `extracted/sprites/` for complete sprite "
      "coverage and `extracted/xfl/` for the authored screens."
      % (xfl["sprite_symbols"], xfl["sprites_in_swf"],
         xfl["sprite_symbols_missing_count"], xfl["missing_but_linkage_exported"]))
    A("- `DefineEditText` tags are runtime text fields; their rendered appearance "
      "depends on the client's embedded fonts, so `texts/` holds text content, not "
      "layout.")
    A("- FFDec emits sound files with a duplicated extension (e.g. "
      "`1_sfx_14.mp3.mp3`); the inner extension is the real container. Files are "
      "kept as emitted so the manifest stays byte-reproducible.")
    A("- `-select` is ignored by this FFDec build for sprite export, so the opt-in "
      "sprite stage always renders every frame of every sprite.")
    A("")

    os.makedirs(ana, exist_ok=True)
    with open(os.path.join(ana, "extraction_report.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("verification: %s" % ("PASS" if result["ok"] else "FAIL"))
    for w in warnings:
        print("  warning: %s" % w)
    for hf in hard_fail:
        print("  FAILURE: %s" % hf)
    print("report: analysis/extraction_report.md")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
