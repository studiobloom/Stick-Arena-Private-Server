#!/usr/bin/env python3
"""
swf_inspect.py -- dependency-free structural inspector for the sab558 SWF.

Reads the original SWF *read-only* and emits machine-readable manifests that
preserve original identifiers (character ids, export names, sprite frame counts,
frame labels, tag offsets) plus the tag tree and resource relationships.

Why a hand-rolled parser instead of scraping the decompiler output:
  * the tag tree in DefineSprite bodies is authoritative in the binary;
  * FFDec's -dumpSWF column alignment is presentation, not data;
  * offsets let any extracted file be traced back to a byte position in the
    original file.

Outputs (all JSON, UTF-8, stable ordering):
  swf_header.json       signature/version/length/rect/fps/frame count/sha256
  tags.json             flat list of every tag incl. nested sprite bodies
  characters.json       id -> definition metadata (type, frames, labels, ...)
  relationships.json    timeline -> child character edges (PlaceObject*)
  as2_strings.json      AVM1 string literals with locations
  summary.json          counts used by the extraction report

Usage:
  python swf_inspect.py <sab558.swf> <outdir>

Confirmed-only policy: every field below is read directly from the file. When a
field cannot be determined it is set to null and listed in summary["unknowns"].
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import zlib
from collections import Counter, OrderedDict

# --------------------------------------------------------------------------
# SWF tag catalogue (only codes observed in sab558 plus common neighbours).
# --------------------------------------------------------------------------
TAG_NAMES = {
    0: "End",
    1: "ShowFrame",
    2: "DefineShape",
    4: "PlaceObject",
    5: "RemoveObject",
    6: "DefineBits",
    7: "DefineButton",
    8: "JPEGTables",
    9: "SetBackgroundColor",
    10: "DefineFont",
    11: "DefineText",
    12: "DoAction",
    13: "DefineFontInfo",
    14: "DefineSound",
    15: "StartSound",
    17: "DefineButtonSound",
    18: "SoundStreamHead",
    19: "SoundStreamBlock",
    20: "DefineBitsLossless",
    21: "DefineBitsJPEG2",
    22: "DefineShape2",
    23: "DefineButtonCxform",
    24: "Protect",
    26: "PlaceObject2",
    28: "RemoveObject2",
    32: "DefineShape3",
    33: "DefineText2",
    34: "DefineButton2",
    35: "DefineBitsJPEG3",
    36: "DefineBitsLossless2",
    37: "DefineEditText",
    39: "DefineSprite",
    43: "FrameLabel",
    45: "SoundStreamHead2",
    46: "DefineMorphShape",
    48: "DefineFont2",
    56: "ExportAssets",
    57: "ImportAssets",
    58: "EnableDebugger",
    59: "DoInitAction",
    60: "DefineVideoStream",
    61: "VideoFrame",
    62: "DefineFontInfo2",
    64: "EnableDebugger2",
    65: "ScriptLimits",
    66: "SetTabIndex",
    69: "FileAttributes",
    70: "PlaceObject3",
    71: "ImportAssets2",
    72: "DoABC",
    73: "DefineFontAlignZones",
    74: "CSMTextSettings",
    75: "DefineFont3",
    76: "SymbolClass",
    77: "Metadata",
    78: "DefineScalingGrid",
    82: "DoABC2",
    83: "DefineShape4",
    84: "DefineMorphShape2",
    86: "DefineSceneAndFrameLabelData",
    87: "DefineBinaryData",
    88: "DefineFontName",
    89: "StartSound2",
    90: "DefineBitsJPEG4",
    91: "DefineFont4",
    93: "EnableTelemetry",
    94: "Metadata2",
}

# tag code -> name of the character-id field it defines (first UI16 of body)
CHARACTER_ID_TAGS = {
    2: "shape", 22: "shape", 32: "shape", 83: "shape",
    11: "text", 33: "text", 37: "edittext",
    7: "button", 34: "button",
    6: "image", 20: "image", 21: "image", 35: "image", 36: "image", 90: "image",
    14: "sound",
    10: "font", 48: "font", 75: "font", 91: "font4",
    46: "morphshape", 84: "morphshape",
    87: "binarydata",
    39: "sprite",
}

SOUND_FORMATS = {
    0: "UNCOMPRESSED", 1: "ADPCM", 2: "MP3", 3: "UNCOMPRESSED_LITTLE_ENDIAN",
    4: "NELLYMOSER_16KHZ", 5: "NELLYMOSER_8KHZ", 6: "NELLYMOSER", 11: "SPEEX",
}
SOUND_RATES = {0: 5512, 1: 11025, 2: 22050, 3: 44100}
SOUND_SIZES = {0: 8, 1: 16}
SOUND_TYPES = {0: "mono", 1: "stereo"}


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def ui32(self):
        return self.u32()

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def f64(self):
        v = struct.unpack_from("<d", self.d, self.p)[0]
        self.p += 8
        return v

    def cstr(self):
        end = self.d.index(b"\x00", self.p)
        s = self.d[self.p:end]
        self.p = end + 1
        return s.decode("utf-8", "replace")


class BitReader:
    """MSB-first bit reader, needed only for the stage RECT."""

    def __init__(self, data: bytes, pos: int):
        self.d = data
        self.bitpos = pos * 8

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.d[self.bitpos >> 3]
            bit = (byte >> (7 - (self.bitpos & 7))) & 1
            v = (v << 1) | bit
            self.bitpos += 1
        return v

    def signed(self, n: int) -> int:
        v = self.bits(n)
        if v & (1 << (n - 1)):
            v -= 1 << n
        return v

    @property
    def bytepos(self) -> int:
        return (self.bitpos + 7) >> 3


# --------------------------------------------------------------------------
# AVM1 (ActionScript 1/2) scanning: constant pools + push string literals.
# --------------------------------------------------------------------------
def scan_avm1_strings(code: bytes):
    """Return (constant_pool_strings, pushed_strings) found in an AVM1 blob.

    ActionConstantPool = 0x88, ActionPush = 0x96. Actions with the high bit set
    carry a UI16 length. Unknown/opaque records are skipped by their length,
    which is exactly how the AVM walks them.
    """
    pool, pushed = [], []
    p = 0
    n = len(code)
    while p < n:
        action = code[p]
        p += 1
        if action == 0:  # ActionEnd
            break
        if action >= 0x80:
            if p + 2 > n:
                break
            length = struct.unpack_from("<H", code, p)[0]
            p += 2
            body = code[p:p + length]
            p += length
            if action == 0x88 and len(body) >= 2:
                r = Reader(body)
                count = r.u16()
                for _ in range(count):
                    if r.p >= len(body):
                        break
                    try:
                        pool.append(r.cstr())
                    except ValueError:
                        break
            elif action == 0x96:
                pushed.extend(_parse_push(body))
        else:
            # single-byte actions with inline operands
            if action == 0x9B:  # ActionDefineFunction: name + params + bodylen
                break  # function body is not walked; nested scan is out of scope
    return pool, pushed


def _parse_push(body: bytes):
    out = []
    r = Reader(body)
    while r.p < len(body):
        t = r.u8()
        try:
            if t == 0:
                out.append(r.cstr())
            elif t == 1:
                out.append(r.f32())
            elif t == 2:
                out.append(None)
            elif t == 3:
                out.append("<undefined>")
            elif t == 4:
                out.append("<register:%d>" % r.u8())
            elif t == 5:
                out.append(bool(r.u8()))
            elif t == 6:
                out.append(r.f64())
            elif t == 7:
                out.append(r.u32())
            elif t == 8:
                out.append("<constant:%d>" % r.u8())
            elif t == 9:
                out.append("<constant:%d>" % r.u16())
            else:
                break
        except (IndexError, struct.error, ValueError):
            break
    return [s for s in out if isinstance(s, str)]


# --------------------------------------------------------------------------
# SWF parsing
# --------------------------------------------------------------------------
class SwfInspector:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self.raw = f.read()
        self.sha256 = hashlib.sha256(self.raw).hexdigest()
        self.tags = []          # flat, ordered
        self.characters = OrderedDict()
        self.edges = []         # {timeline, timeline_type, frame, child, depth, tag}
        self.strings = []       # {location, kind, value}
        self.unknowns = []
        self._parse()

    # -- header ---------------------------------------------------------
    def _parse(self):
        raw = self.raw
        sig = raw[0:3]
        if sig not in (b"FWS", b"CWS", b"ZWS"):
            raise SystemExit("not a SWF: signature=%r" % sig)
        version = raw[3]
        declared_len = struct.unpack_from("<I", raw, 4)[0]
        if sig == b"CWS":
            body = zlib.decompress(raw[8:])
            self.compression = "zlib"
            data = raw[0:8] + body
        elif sig == b"ZWS":
            raise SystemExit("LZMA-compressed SWF not supported by this inspector")
        else:
            data = raw
            self.compression = "none"
        self.data = data
        self.header = {
            "path": os.path.abspath(self.path).replace("\\", "/"),
            "signature": sig.decode("ascii"),
            "compression": self.compression,
            "swf_version": version,
            "declared_file_length": declared_len,
            "actual_file_length": len(raw),
            "declared_length_matches_actual": declared_len == len(raw),
            "sha256": self.sha256,
        }
        if declared_len != len(raw):
            self.unknowns.append(
                "header declared_file_length (%d) != actual file size (%d); "
                "the field was likely patched by a previous editor. Parsing uses "
                "actual bytes." % (declared_len, len(raw))
            )

        br = BitReader(data, 8)
        nbits = br.bits(5)
        rect = [br.signed(nbits) for _ in range(4)]
        self.header["stage_rect_twips"] = {
            "xmin": rect[0], "xmax": rect[1], "ymin": rect[2], "ymax": rect[3]
        }
        self.header["stage_dimensions_px"] = {
            "width": (rect[1] - rect[0]) / 20.0,
            "height": (rect[3] - rect[2]) / 20.0,
        }
        p = br.bytepos
        fps_raw = struct.unpack_from("<H", data, p)[0]
        p += 2
        self.header["frame_rate_fixed8_8"] = fps_raw
        self.header["frame_rate_fps"] = round(fps_raw / 256.0, 4)
        frame_count = struct.unpack_from("<H", data, p)[0]
        p += 2
        self.header["main_timeline_frame_count"] = frame_count
        self.header["tag_stream_offset"] = p

        self._parse_tags(p, len(data), timeline=0, timeline_type="main",
                         depth=0, parent=None)

        self.header["main_timeline_showframe_count"] = sum(
            1 for t in self.tags
            if t["code"] == 1 and t["depth"] == 0
        )
        if self.header["main_timeline_showframe_count"] != frame_count:
            self.unknowns.append(
                "main timeline header frame count (%d) != counted ShowFrame tags (%d)"
                % (frame_count, self.header["main_timeline_showframe_count"])
            )

    def _parse_tags(self, start, end, timeline, timeline_type, depth, parent):
        p = start
        index = 0
        frame = 1
        while p + 2 <= end:
            code_len = struct.unpack_from("<H", self.data, p)[0]
            code = code_len >> 6
            length = code_len & 0x3F
            hdr = 2
            if length == 0x3F:
                length = struct.unpack_from("<I", self.data, p + 2)[0]
                hdr = 6
            body_start = p + hdr
            body_end = body_start + length
            if body_end > end:
                self.unknowns.append(
                    "tag at offset %d (code %d) claims %d bytes past end of container; truncated"
                    % (p, code, body_end - end)
                )
                body_end = end
            rec = OrderedDict()
            rec["offset"] = p
            rec["code"] = code
            rec["name"] = TAG_NAMES.get(code, "Unknown_%d" % code)
            rec["length"] = length
            rec["depth"] = depth
            rec["timeline"] = timeline
            rec["timeline_type"] = timeline_type
            rec["frame"] = frame
            rec["parent_sprite"] = parent
            rec["index"] = index
            if code not in TAG_NAMES:
                self.unknowns.append(
                    "unknown tag code %d at offset %d (len %d)" % (code, p, length)
                )
            self._annotate(rec, body_start, body_end, timeline, timeline_type,
                           frame, depth)
            self.tags.append(rec)
            index += 1

            if code == 1:  # ShowFrame
                frame += 1
            elif code == 39:  # DefineSprite
                sid = struct.unpack_from("<H", self.data, body_start)[0]
                declared = struct.unpack_from("<H", self.data, body_start + 2)[0]
                self._parse_tags(body_start + 4, body_end, sid, "sprite",
                                 depth + 1, sid)
                ch = self.characters.setdefault(sid, {})
                ch["declared_frame_count"] = declared
                counted = sum(1 for t in self.tags
                              if t["parent_sprite"] == sid and t["code"] == 1)
                ch["counted_showframe_tags"] = counted
                if counted != declared:
                    self.unknowns.append(
                        "sprite %d declares %d frames but contains %d ShowFrame tags"
                        % (sid, declared, counted)
                    )
            p = body_end
            if code == 0:  # End
                break
        return p

    def _annotate(self, rec, body_start, body_end, timeline, timeline_type,
                  frame, depth):
        code = rec["code"]
        body = self.data[body_start:body_end]
        location = self._location(timeline, timeline_type, frame)
        rec["location"] = location

        if code in CHARACTER_ID_TAGS:
            cid = struct.unpack_from("<H", body, 0)[0]
            rec["character_id"] = cid
            kind = CHARACTER_ID_TAGS[code]
            ch = self.characters.setdefault(cid, OrderedDict())
            ch.setdefault("character_id", cid)
            ch.setdefault("definitions", []).append(
                {"tag": rec["name"], "code": code, "offset": rec["offset"],
                 "length": rec["length"], "timeline": timeline,
                 "timeline_type": timeline_type}
            )
            ch.setdefault("kinds", [])
            if kind not in ch["kinds"]:
                ch["kinds"].append(kind)
            if kind == "sound":
                self._annotate_sound(ch, body)
            elif kind == "image":
                self._annotate_image(ch, code, body)
            elif kind in ("font", "font4"):
                self._annotate_font(ch, body)
            elif kind == "sprite":
                ch["timeline_type"] = "sprite"
                ch["frame_labels"] = []
                ch["child_ids"] = []
            elif kind == "shape":
                ch.setdefault("frame_labels", [])
                ch.setdefault("child_ids", [])

        elif code == 56:  # ExportAssets
            if len(body) >= 2:
                count = struct.unpack_from("<H", body, 0)[0]
                r = Reader(body, 2)
                pairs = []
                for _ in range(count):
                    try:
                        cid = r.u16()
                        name = r.cstr()
                    except (IndexError, ValueError, struct.error):
                        break
                    pairs.append({"character_id": cid, "export_name": name})
                    ch = self.characters.setdefault(cid, OrderedDict())
                    ch.setdefault("character_id", cid)
                    ch.setdefault("export_names", [])
                    if name not in ch["export_names"]:
                        ch["export_names"].append(name)
                    ch.setdefault("kinds", [])
                    if "export" not in ch["kinds"]:
                        ch["kinds"].append("export")
                rec["export_assets"] = pairs

        elif code == 76:  # SymbolClass
            if len(body) >= 2:
                count = struct.unpack_from("<H", body, 0)[0]
                r = Reader(body, 2)
                pairs = []
                for _ in range(count):
                    try:
                        cid = r.u16()
                        cls = r.cstr()
                    except (IndexError, ValueError, struct.error):
                        break
                    pairs.append({"character_id": cid, "class_name": cls})
                    ch = self.characters.setdefault(cid, OrderedDict())
                    ch.setdefault("character_id", cid)
                    ch.setdefault("symbol_classes", []).append(cls)
                rec["symbol_classes"] = pairs

        elif code == 43:  # FrameLabel
            try:
                name = Reader(body).cstr()
            except (ValueError, IndexError):
                name = None
            rec["frame_label"] = name
            if name is not None:
                self._record_frame_label(timeline, name, frame, rec["offset"])

        elif code in (26, 70):  # PlaceObject2 / PlaceObject3
            child, dpt, has_char = self._place_object(body, code)
            rec["place_depth"] = dpt
            if child is not None:
                rec["child_character_id"] = child
                self.edges.append({
                    "timeline": timeline,
                    "timeline_type": timeline_type,
                    "frame": frame,
                    "child_character_id": child,
                    "depth": dpt,
                    "tag": rec["name"],
                    "offset": rec["offset"],
                })
                if timeline in self.characters:
                    ch = self.characters[timeline]
                    ch.setdefault("child_ids", [])
                    if child not in ch["child_ids"]:
                        ch["child_ids"].append(child)

        elif code == 28:  # RemoveObject2
            if len(body) >= 2:
                rec["place_depth"] = struct.unpack_from("<H", body, 0)[0]

        elif code in (12, 59):  # DoAction / DoInitAction
            sprite = None
            payload = body
            if code == 59 and len(body) >= 2:
                sprite = struct.unpack_from("<H", body, 0)[0]
                payload = body[2:]
                rec["init_sprite_id"] = sprite
            pool, pushed = scan_avm1_strings(payload)
            rec["avm1_constant_pool_count"] = len(pool)
            rec["avm1_push_string_count"] = len(pushed)
            for s in pool:
                self.strings.append({"location": location, "kind": "constant_pool",
                                     "value": s, "offset": rec["offset"]})
            for s in pushed:
                self.strings.append({"location": location, "kind": "push",
                                     "value": s, "offset": rec["offset"]})

        elif code == 9:  # SetBackgroundColor
            if len(body) >= 3:
                rec["background_rgb"] = list(body[0:3])

        elif code == 65:  # ScriptLimits
            if len(body) >= 4:
                rec["max_recursion_depth"], rec["script_timeout_seconds"] = struct.unpack(
                    "<HH", body[0:4])
            if rec.get("script_timeout_seconds", 0) != 60:
                pass

        elif code == 69:  # FileAttributes
            if len(body) >= 1:
                rec["file_attributes"] = body[0]

        elif code == 77:  # Metadata
            try:
                rec["metadata_xml"] = body.rstrip(b"\x00").decode("utf-8", "replace")
            except Exception:
                pass

        elif code == 14:  # DefineSound
            rec["sound_character_id"] = struct.unpack_from("<H", body, 0)[0]

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _location(timeline, timeline_type, frame):
        if timeline_type == "main":
            return "main_timeline/frame_%d" % frame
        return "DefineSprite_%d/frame_%d" % (timeline, frame)

    def _record_frame_label(self, timeline, name, frame, offset):
        if timeline == 0:
            self.header.setdefault("main_timeline_frame_labels", []).append(
                {"name": name, "frame": frame, "offset": offset})
        else:
            ch = self.characters.setdefault(timeline, OrderedDict())
            ch.setdefault("frame_labels", []).append(
                {"name": name, "frame": frame, "offset": offset})

    @staticmethod
    def _place_object(body, code):
        """Decode (CharacterId, Depth) from PlaceObject2 / PlaceObject3.

        SWF layout (spec v19) is Flags, **Depth**, then CharacterId -- not
        CharacterId first. Getting this backwards silently swaps every
        placement edge, so it is spelled out here.

        PlaceObject2: Flags UI8, Depth UI16, [CharacterId UI16 if HasCharacter], ...
        PlaceObject3: Flags1 UI8, Flags2 UI8, Depth UI16,
                      [ClassName STRING if HasClassName],
                      [CharacterId UI16 if HasCharacter], ...
        """
        if code == 26:
            if len(body) < 3:
                return None, None, False
            flags = body[0]
            has_char = bool(flags & 0x02)          # HasCharacter
            dpt = struct.unpack_from("<H", body, 1)[0]
            child = None
            if has_char and len(body) >= 5:
                child = struct.unpack_from("<H", body, 3)[0]
            return child, dpt, has_char
        # PlaceObject3
        if len(body) < 4:
            return None, None, False
        flags1, flags2 = body[0], body[1]
        has_char = bool(flags1 & 0x02)             # HasCharacter
        dpt = struct.unpack_from("<H", body, 2)[0]
        p = 4
        if flags2 & 0x04:                          # HasClassName
            try:
                p = body.index(b"\x00", p) + 1
            except ValueError:
                return None, dpt, False
        child = None
        if has_char and len(body) >= p + 2:
            child = struct.unpack_from("<H", body, p)[0]
        return child, dpt, has_char

    def _annotate_sound(self, ch, body):
        # DefineSound: UI16 soundId, then packed UB[4] format / UB[2] rate /
        # UB[1] size / UB[1] type, then UI32 sampleCount.
        if len(body) < 7:
            return
        sid = struct.unpack_from("<H", body, 0)[0]
        packed = body[2]
        fmt = packed >> 4
        rate = (packed >> 2) & 0x03
        size = (packed >> 1) & 0x01
        typ = packed & 0x01
        count = struct.unpack_from("<I", body, 3)[0]
        ch["sound"] = {
            "format": SOUND_FORMATS.get(fmt, "UNKNOWN_%d" % fmt),
            "rate_hz": SOUND_RATES.get(rate),
            "sample_size_bits": SOUND_SIZES.get(size),
            "channels": SOUND_TYPES.get(typ),
            "sample_count": count,
            "approx_duration_seconds": (round(count / float(SOUND_RATES.get(rate, 0)), 4)
                                        if SOUND_RATES.get(rate) else None),
        }

    def _annotate_image(self, ch, code, body):
        info = {"tag": TAG_NAMES.get(code)}
        if code in (21, 35, 90) and len(body) >= 2:
            r = Reader(body, 2)
            if code == 90 and len(body) >= 6:
                r.p = 6  # charId + DeblockParam + alphaDataOffset
            data = body[r.p:]
            if data[0:2] == b"\xff\xd8":
                info["format"] = "jpeg"
                info["has_alpha"] = code in (35, 90)
            elif data[0:8] == b"\x89PNG\r\n\x1a\n":
                info["format"] = "png"
                info["has_alpha"] = True
            else:
                info["format"] = "unknown"
            # JPEG SOF dimensions are cheap to read and avoid a second tool.
            dims = _jpeg_dimensions(data)
            if dims:
                info["width"], info["height"] = dims
        elif code in (20, 36) and len(body) >= 7:
            fmt = body[2]
            w, h = struct.unpack_from("<HH", body, 3)
            info["format"] = {3: "png8", 4: "png32", 5: "argb4444",
                              6: "rgb555", 7: "rgb565"}.get(fmt, "lossless_%d" % fmt)
            info["width"], info["height"] = w, h
            info["has_alpha"] = code == 36 or fmt in (3, 4, 5)
        ch["image"] = info

    def _annotate_font(self, ch, body):
        """DefineFont/2/3 store the font name after the glyph-offset table.
        We only record what is unambiguous here; the TTF export carries the
        full metrics. DefineFont4 (CFF) has no AVM1-visible name."""
        ch.setdefault("font", {})
        if ch["font"].get("name"):
            return
        if body[:2] != b"\x00\x00" and len(body) > 4:
            # best-effort: the name is the first null-terminated run after the
            # glyph table; FFDec's TTF/WOFF export is the authoritative source.
            try:
                name = Reader(body, 2).cstr()
            except (ValueError, IndexError):
                name = None
            if name and all(32 <= ord(c) < 127 for c in name):
                ch["font"]["name"] = name

    # -- emit -----------------------------------------------------------
    def dump(self, outdir):
        os.makedirs(outdir, exist_ok=True)

        def write(name, obj):
            path = os.path.join(outdir, name)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)
                f.write("\n")
            return path

        # character index: sort numerically for stable diffs
        chars = OrderedDict()
        for cid in sorted(self.characters):
            ch = self.characters[cid]
            ch.setdefault("character_id", cid)
            ch.setdefault("export_names", [])
            ch.setdefault("kinds", [])
            if "sprite" in ch.get("kinds", []):
                ch.setdefault("frame_labels", [])
                ch.setdefault("child_ids", [])
            chars[str(cid)] = ch

        tag_counts = Counter(t["name"] for t in self.tags)
        summary = OrderedDict()
        summary["header"] = self.header
        summary["tag_counts"] = dict(sorted(tag_counts.items(), key=lambda kv: -kv[1]))
        summary["tag_total_including_nested"] = len(self.tags)
        summary["top_level_tag_count"] = sum(1 for t in self.tags if t["depth"] == 0)
        summary["character_count"] = len(chars)
        summary["character_kind_counts"] = dict(sorted(
            Counter(k for c in chars.values() for k in c.get("kinds", [])).items(),
            key=lambda kv: -kv[1]))
        summary["export_asset_count"] = sum(
            len(c.get("export_names", [])) for c in chars.values())
        summary["relationship_edge_count"] = len(self.edges)
        summary["avm1_string_literal_count"] = len(self.strings)
        summary["avm1_unique_string_count"] = len({s["value"] for s in self.strings})
        summary["unknowns"] = self.unknowns
        summary["timeline_frame_totals"] = {
            "main": self.header["main_timeline_frame_count"],
            "sprites": sum(c.get("counted_showframe_tags", 0)
                           for c in chars.values() if "sprite" in c.get("kinds", [])),
        }

        write("swf_header.json", self.header)
        write("tags.json", {
            "note": "Flat tag list in file order. Nested tags of a DefineSprite "
                    "follow their parent with depth+1 and parent_sprite set.",
            "tags": self.tags,
        })
        write("characters.json", {
            "note": "Keyed by original SWF character id. No ids are renumbered.",
            "characters": chars,
        })
        write("relationships.json", {
            "note": "PlaceObject2/PlaceObject3 edges: which timeline places which "
                    "character id at which frame.",
            "edges": self.edges,
        })
        write("as2_strings.json", {
            "note": "String literals found in AVM1 ActionConstantPool/ActionPush "
                    "records. Locations use the original timeline/frame numbering.",
            "strings": self.strings,
        })
        write("summary.json", summary)

        # human-readable string index, grouped, for architecture analysis
        grouped = OrderedDict()
        for s in self.strings:
            grouped.setdefault(s["value"], []).append(s["location"])
        lines = ["# AVM1 string literals in sab558.swf",
                 "# value<TAB>occurrences<TAB>first location(s)", ""]
        for value, locs in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            uniq = sorted(set(locs))
            shown = ", ".join(uniq[:4]) + (" ..." if len(uniq) > 4 else "")
            lines.append("%s\t%d\t%s" % (value.replace("\t", " ").replace("\n", " "),
                                         len(locs), shown))
        with open(os.path.join(outdir, "as2_strings.txt"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        return summary


def _jpeg_dimensions(data: bytes):
    if data[0:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack_from(">H", data, i + 2)[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack_from(">HH", data, i + 5)
            return w, h
        i += 2 + seg_len
    return None


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    swf, outdir = argv[1], argv[2]
    insp = SwfInspector(swf)
    summary = insp.dump(outdir)
    h = summary["header"]
    print("SWF      : %s" % h["path"])
    print("sha256   : %s" % h["sha256"])
    print("version  : %d (%s)" % (h["swf_version"], h["compression"]))
    print("stage    : %gx%g px @ %g fps, %d main frames"
          % (h["stage_dimensions_px"]["width"], h["stage_dimensions_px"]["height"],
             h["frame_rate_fps"], h["main_timeline_frame_count"]))
    print("tags     : %d total / %d top-level"
          % (summary["tag_total_including_nested"], summary["top_level_tag_count"]))
    print("chars    : %d (%s)" % (summary["character_count"],
                                  summary["character_kind_counts"]))
    print("edges    : %d" % summary["relationship_edge_count"])
    print("strings  : %d literals / %d unique"
          % (summary["avm1_string_literal_count"], summary["avm1_unique_string_count"]))
    if summary["unknowns"]:
        print("unknowns : %d (see summary.json)" % len(summary["unknowns"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
