#!/usr/bin/env python3
"""
link_exports.py -- bind extracted files back to their original SWF identifiers.

Reads the manifests produced by swf_inspect.py (characters.json, tags.json,
swf_header.json) and walks reference/sab558/extracted/, then writes:

  manifests/export_manifest.json   one record per extracted file:
                                   path, kind, character id, export names,
                                   timeline, frame, byte size, sha256,
                                   and the byte offset of the defining tag
  manifests/export_manifest.csv    flat index (path,kind,character_id,frame,bytes)
  manifests/coverage.json          which character ids have which representations,
                                   and which do not have any (unresolved)

Nothing here guesses: if a file name cannot be tied to an id with certainty the
record is emitted with character_id = null and a parse_note explaining why.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict, defaultdict



def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_character_id(name: str):
    """Pull the numeric SWF character id out of an FFDec output name.

    FFDec uses the original id verbatim, e.g. 'DefineSprite_237',
    'DefineSprite_7858_petMC06', '1_sfx_14.mp3.mp3', '233.svg'.
    """
    m = re.match(r"^Define[A-Za-z0-9]*?_(\d+)(?:_(.*))?$", name)
    if m:
        return int(m.group(1)), (m.group(2) or None), "define_prefix"
    m = re.match(r"^(\d+)(?:_(.*))?$", name)
    if m:
        return int(m.group(1)), (m.group(2) or None), "leading_id"
    m = re.match(r"^(\d+)\b", name)
    if m:
        return int(m.group(1)), None, "leading_id"
    return None, None, "unresolved"


def classify(relpath: str):
    """Map an extracted relative path to (kind, character_id, frame, timeline,
    note). Timeline is the owning sprite id for sprite-scoped output."""
    parts = relpath.replace("\\", "/").split("/")
    top = parts[0]
    stem = os.path.splitext(parts[-1])[0]
    note = None

    if top == "scripts":
        # scripts/<...>   : AS2 code. Sprite/button scope is encoded in the path.
        scope = parts[1] if len(parts) > 2 else None
        cid = None
        timeline = None
        frame = None
        if scope:
            m = re.match(r"^DefineSprite_(\d+)(?:_(.*))?$", scope)
            if m:
                cid = int(m.group(1)); timeline = cid
            else:
                m = re.match(r"^Define(Button2?|Button)_(\d+)(?:_(.*))?$", scope)
                if m:
                    cid = int(m.group(2))
                elif re.match(r"^frame_\d+$", scope):
                    frame = int(scope.split("_")[1])
                elif scope == "__Packages":
                    note = "ActionScript package path"
                else:
                    note = "script scope not recognised"
        else:
            note = "top-level ActionScript class"
        return "script", cid, frame, timeline, note

    if top == "sprites":
        # sprites/DefineSprite_<id>[_name]/<frame>.svg
        cid, name, _ = parse_character_id(parts[1]) if len(parts) > 2 else (None, None, None)
        frame = None
        if stem.isdigit():
            frame = int(stem)
        return "sprite_frame", cid, frame, cid, note

    if top == "xfl":
        # XFL project. LIBRARY items carry the original ids; everything else
        # (DOMDocument.xml, bin/M <id> <ts>.dat, PublishSettings.xml) is project
        # scaffolding without a character identity.
        cid = None
        if len(parts) >= 3 and parts[1] == "LIBRARY":
            m = re.match(r"^(?:Symbol|Bitmap|Shape|Sound|Font) (\d+)\.[A-Za-z0-9]+$", parts[2])
            if m:
                cid = int(m.group(1))
            else:
                m = re.match(r"^sound(\d+)\.\w+$", parts[2])
                if m:
                    cid = int(m.group(1))
                else:
                    note = "XFL library item with an unrecognised name"
        elif len(parts) >= 3 and parts[1] == "bin":
            m = re.match(r"^M (\d+) ", parts[2])
            if m:
                cid = int(m.group(1))
                note = "XFL media blob (bin/) for this character id"
        return "xfl", cid, None, None, note

    if top == "buttons":
        # buttons/DefineButton2_<id>/<state>.png (up, over, down, hittest)
        if len(parts) >= 3:
            cid, _name, _how = parse_character_id(parts[1])
        else:
            cid, _name, _how = parse_character_id(stem)
        return "button", cid, None, None, note

    if top == "swf_xml":
        # Whole-file artefact, not tied to a single character.
        return "swf_xml", None, None, None, "complete SWF->XML dump of the whole file"

    if top == "frames":
        # frames/<n>.png  -- main timeline frames (character 0)
        frame = int(stem) if stem.isdigit() else None
        return "main_frame", 0, frame, 0, note

    kind_map = {
        "shapes": "shape",
        "morphshapes": "morphshape",
        "images": "image",
        "sounds": "sound",
        "fonts": "font",
        "fonts_woff": "font",
        "font4": "font4",
        "texts": "text",
        "binaryData": "binarydata",
        "symbolClass": "symbolclass",
    }
    kind = kind_map.get(top)
    if kind is None:
        return "unknown", None, None, None, "unrecognised top-level output dir"
    cid, _name, how = parse_character_id(stem)
    if cid is None:
        note = "no character id in file name"
    return kind, cid, None, None, note


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    ref = os.path.abspath(argv[1])
    man = os.path.join(ref, "manifests")
    out = os.path.join(ref, "extracted")

    chars = load_json(os.path.join(man, "characters.json"))["characters"]
    tags = load_json(os.path.join(man, "tags.json"))["tags"]
    header = load_json(os.path.join(man, "swf_header.json"))

    # character id -> defining tag offset (first definition in file order)
    first_def = {}
    for t in tags:
        cid = t.get("character_id")
        if cid is not None and t["name"].startswith("Define") and cid not in first_def:
            first_def[cid] = t["offset"]

    def char_info(cid):
        if cid is None:
            return None
        c = chars.get(str(cid))
        if not c:
            return None
        return {
            "character_id": cid,
            "kinds": c.get("kinds", []),
            "export_names": c.get("export_names", []),
            "frame_labels": c.get("frame_labels", []),
            "declared_frame_count": c.get("declared_frame_count"),
            "def_offset": first_def.get(cid),
        }

    records = []
    for dirpath, dirnames, filenames in os.walk(out):
        # _unexpected/ holds quarantined decompiler output (never published).
        dirnames[:] = sorted(d for d in dirnames if d != "_unexpected")
        filenames = sorted(filenames)
        for fn in filenames:
            if fn == ".stage_ok":
                continue
            abspath = os.path.join(dirpath, fn)
            rel = os.path.relpath(abspath, out).replace("\\", "/")
            kind, cid, frame, timeline, note = classify(rel)
            size = os.path.getsize(abspath)
            rec = OrderedDict()
            rec["path"] = rel
            rec["kind"] = kind
            rec["character_id"] = cid
            rec["frame"] = frame
            rec["timeline_character_id"] = timeline
            rec["bytes"] = size
            rec["sha256"] = sha256_file(abspath)
            rec["character"] = char_info(cid)
            if note:
                rec["parse_note"] = note
            records.append(rec)

    records.sort(key=lambda r: (r["kind"], r["path"]))

    # ---- write full manifest
    with open(os.path.join(man, "export_manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "source_swf": header["path"],
            "source_swf_sha256": header["sha256"],
            "note": "Every extracted file, linked to the original SWF character id. "
                    "character_id 0 denotes the main timeline. Paths are relative to "
                    "reference/sab558/extracted/.",
            "file_count": len(records),
            "total_bytes": sum(r["bytes"] for r in records),
            "files": records,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # ---- flat csv index
    with open(os.path.join(man, "export_manifest.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "kind", "character_id", "timeline_character_id",
                    "frame", "bytes", "sha256", "export_names"])
        for r in records:
            names = ";".join((r["character"] or {}).get("export_names", []))
            w.writerow([r["path"], r["kind"], "" if r["character_id"] is None else r["character_id"],
                        "" if r["timeline_character_id"] is None else r["timeline_character_id"],
                        "" if r["frame"] is None else r["frame"], r["bytes"], r["sha256"], names])

    # ---- coverage: which ids are represented, which are not
    by_kind = defaultdict(set)
    for r in records:
        if r["character_id"] is not None:
            by_kind[r["kind"]].add(r["character_id"])

    expected = defaultdict(set)
    empty_defs = []
    extracted_ids = set()
    for ids in by_kind.values():
        extracted_ids |= ids
    for cid_s, c in chars.items():
        cid = int(cid_s)
        kinds = [k for k in c.get("kinds", []) if k != "export"]
        for k in kinds:
            expected[k].add(cid)
        defs = c.get("definitions", [])
        smallest = min((d.get("length", 0) for d in defs), default=None)
        if "sprite" in kinds and (c.get("declared_frame_count") or 0) == 0:
            # Zero-frame sprites are class/linkage holders: they can still own
            # scripts, but they can never produce a rendered frame.
            empty_defs.append({"character_id": cid, "kinds": kinds,
                               "tag": defs[0].get("tag") if defs else None,
                               "tag_length": defs[0].get("length") if defs else None,
                               "reason": "zero-frame sprite (class / linkage stub)"})
            continue
        if cid in extracted_ids:
            continue  # produced at least one file; nothing to explain
        if defs and smallest is not None and smallest <= 32 and not c.get("export_names"):
            empty_defs.append({"character_id": cid, "kinds": kinds,
                               "tag": defs[0].get("tag"),
                               "tag_length": defs[0].get("length"),
                               "reason": "definition carries no payload"})

    empty_ids = {(e["character_id"], k) for e in empty_defs for k in e["kinds"]}

    # expected-kind -> extracted-kind alias
    alias = {
        "shape": ["shape"],
        "morphshape": ["morphshape"],
        "image": ["image"],
        "sound": ["sound"],
        "font": ["font", "font4"],
        "font4": ["font4"],
        "text": ["text"],
        "edittext": ["text"],
        "button": ["button"],
        "binarydata": ["binarydata"],
        "sprite": ["sprite_frame"],
    }

    unresolved = []
    for kind, ids in sorted(expected.items()):
        got = set()
        for gk in alias.get(kind, [kind]):
            got |= by_kind.get(gk, set())
        missing = sorted(ids - got)
        # ids that structurally cannot produce a file, or that are already
        # represented by some other extracted artefact (e.g. an XFL media blob),
        # are not "unresolved"
        missing_real = [i for i in missing
                        if (i, kind) not in empty_ids and i not in extracted_ids]
        if missing_real:
            unresolved.append({
                "expected_kind": kind,
                "missing_count": len(missing_real),
                "missing_ids": missing_real[:200],
                "missing_ids_truncated": len(missing_real) > 200,
            })

    coverage = OrderedDict()
    coverage["note"] = ("expected_* counts come from the SWF tag tree; extracted_* "
                        "counts come from files actually on disk. A mismatch means the "
                        "decompiler did not emit that resource and it is listed under "
                        "unresolved.")
    coverage["extracted_counts"] = {k: len(v) for k, v in sorted(by_kind.items())}
    coverage["expected_counts"] = {k: len(v) for k, v in sorted(expected.items())}
    coverage["file_counts_by_kind"] = dict(sorted(
        Counter(r["kind"] for r in records).items()))
    coverage["unresolved"] = unresolved
    coverage["empty_definitions"] = empty_defs[:500]
    coverage["empty_definition_count"] = len(empty_defs)
    coverage["files_without_character_id"] = [
        {"path": r["path"], "kind": r["kind"], "parse_note": r.get("parse_note")}
        for r in records if r["character_id"] is None
    ][:500]

    with open(os.path.join(man, "coverage.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(coverage, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("linked %d files, %.1f MB"
          % (len(records), sum(r["bytes"] for r in records) / 1e6))
    print("by kind: %s" % coverage["file_counts_by_kind"])
    if unresolved:
        for u in unresolved:
            print("  unresolved %s: %d ids not extracted"
                  % (u["expected_kind"], u["missing_count"]))
    else:
        print("  no unresolved character kinds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
