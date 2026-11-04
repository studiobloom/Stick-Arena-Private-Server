#!/usr/bin/env python3
"""
build_systems_index.py -- turn the extracted 558 client into a searchable,
source-grounded index of game systems.

It reads (never modifies) the existing extraction:

  extracted/scripts/as/frame_1/DoAction.as      the game logic (AS2)
  extracted/scripts/as/frame_*/DoAction.as      per-screen logic
  extracted/sprites/DefineSprite_<id>_*/        rendered sprite frames
  manifests/characters.json                     ids, export names, frame labels
  manifests/relationships.json                  timeline -> child placements
  manifests/export_manifest.json                file per character id
  analysis/settings558b.json                    parsed 558 client settings
  htdocs/stickarena/mapEditorTiles.csv          tile collision table

and writes:

  analysis/systems/weapons.json          weapon table decoded from the AS source
  analysis/systems/animations.json       weapon animation clips + durations
  analysis/systems/sounds.json           export name -> character id -> file
  analysis/systems/tiles.json            collision shapes + tile sets
  analysis/systems/constants.json        named constants, each verified against
                                         the source line it is quoted from
  analysis/systems/semantic_index.json   system -> scripts/symbols/assets/server
  analysis/visuals/index.html            clickable contact sheets (no new assets)

Every id is validated against manifests/characters.json; every quoted source
line is re-read and matched. The script fails loudly instead of emitting a
half-true index.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.dirname(HERE)                      # reference/sab558
AS = os.path.join(REF, "extracted", "scripts", "as")
SPR = os.path.join(REF, "extracted", "sprites")
MAN = os.path.join(REF, "manifests")
ANA = os.path.join(REF, "analysis")
SYS = os.path.join(ANA, "systems")
VIS = os.path.join(ANA, "visuals")
REPO = os.path.dirname(os.path.dirname(REF))     # repo root

F1 = os.path.join(AS, "frame_1", "DoAction.as")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().split("\n")


def fail(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 1. Weapons: parse the initializer out of the ActionScript
# ---------------------------------------------------------------------------
def split_args(s):
    out, cur, q = [], "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_weapons():
    src = open(F1, encoding="utf-8").read()
    m = re.search(r"function weaponType\(([^)]*)\)\s*\{(.*?)\n\}", src, re.S)
    if not m:
        fail("weaponType constructor not found")
    params = [p.strip() for p in m.group(1).split(",")]
    body = m.group(2)
    fields = OrderedDict()
    for fm in re.finditer(r"this\.(\w+)\s*=\s*([\w]+);", body):
        fields[fm.group(1)] = fm.group(2)
    # map constructor parameter -> the field that stores it
    param_field = OrderedDict()
    for fld, src_param in fields.items():
        if src_param in params and src_param not in param_field:
            param_field[src_param] = fld

    calls = re.findall(r"weapons\[(\d+)\]\s*=\s*new weaponType\((.*?)\);", src)
    if not calls:
        fail("initializeWeapons() table not found")
    weapons = []
    for idx, argstr in calls:
        args = split_args(argstr)
        rec = OrderedDict()
        rec["id"] = int(idx)
        for i, p in enumerate(params):
            if i >= len(args):
                break
            key = param_field.get(p, p)
            val = args[i]
            if val in ("true", "false"):
                rec[key] = val == "true"
            elif re.fullmatch(r"-?\d+", val):
                rec[key] = int(val)
            elif re.fullmatch(r"-?\d+\.\d+", val):
                rec[key] = float(val)
            else:
                rec[key] = val.strip("\"'")
        weapons.append(rec)
    num = re.search(r"numWeapons\s*=\s*(\d+)", src)
    return weapons, params, int(num.group(1)) if num else len(weapons)


# ---------------------------------------------------------------------------
# 2. Animation clips behind the weapon label table
# ---------------------------------------------------------------------------
def annotate_weapons(weapons, anim):
    """Add derived values and cross-check them against the animation table."""
    labels = {a["label"] for a in anim}
    for w in weapons:
        variants = sum(1 for n in range(1, 4)
                       if "%sAttack%d" % (w.get("attackAnim"), n) in labels)
        w["attack_variants_in_animation_table"] = variants
        w["variants_field_matches_table"] = (variants == w.get("variations"))
        cd = w.get("qxdMlq")
        w["cooldown_ms"] = cd * 33 if isinstance(cd, int) else None
        w["damage_per_second"] = (round(w["damage"] / (w["cooldown_ms"] / 1000.0), 2)
                                  if cd and w.get("damage") else None)
    return weapons


def parse_weapon_animations(chars, edges):
    clip_root = 2530          # gfoKHPq, the arm/weapon clip
    labels = chars[str(clip_root)].get("frame_labels", [])
    by_frame = {}
    for e in edges:
        if e["timeline"] == clip_root:
            by_frame.setdefault(e["frame"], e["child_character_id"])
    # a placement at frame N stays until replaced; fill forward
    current = None
    filled = {}
    for f in range(1, chars[str(clip_root)]["declared_frame_count"] + 1):
        if f in by_frame:
            current = by_frame[f]
        filled[f] = current
    out = []
    for lab in labels:
        cid = filled.get(lab["frame"])
        info = chars.get(str(cid), {}) if cid else {}
        out.append(OrderedDict([
            ("label", lab["name"]),
            ("frame_in_gfoKHPq", lab["frame"]),
            ("clip_character_id", cid),
            ("clip_frames", info.get("declared_frame_count")),
            ("clip_seconds_at_34fps", round(info["declared_frame_count"] / 34.0, 3)
             if info.get("declared_frame_count") else None),
        ]))
    return clip_root, out


# ---------------------------------------------------------------------------
# 3. Sounds: attachSound("name.wav") -> character id -> extracted file
# ---------------------------------------------------------------------------
def parse_sounds(chars, manifest):
    by_export = {}
    for cid, v in chars.items():
        for n in v.get("export_names", []):
            by_export.setdefault(n, int(cid))
    file_by_id = {}
    for rec in manifest["files"]:
        if rec["kind"] == "sound" and rec["character_id"] is not None:
            file_by_id.setdefault(rec["character_id"], rec["path"])
    lower = {}
    for n in by_export:
        lower.setdefault(n.lower(), n)
    src = open(F1, encoding="utf-8").read()
    used = []
    seen = set()
    for m in re.finditer(r'attachSound\("([^"]+)"\)', src):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        cid = by_export.get(name)
        rec = OrderedDict([
            ("attach_sound_name", name),
            ("character_id", cid),
            ("file", file_by_id.get(cid)),
            ("resolves", cid is not None),
        ])
        if cid is None:
            near = lower.get(name.lower())
            if near:
                rec["case_mismatch_with_export_name"] = near
                rec["case_mismatch_character_id"] = by_export[near]
            else:
                rec["note"] = "no ExportAssets name matches this string"
        used.append(rec)
    missing = [u["attach_sound_name"] for u in used if not u["resolves"]]
    return used, missing


# ---------------------------------------------------------------------------
# 4. Tiles and collision shapes
# ---------------------------------------------------------------------------
def parse_tiles(chars):
    csv_path = os.path.join(REPO, "htdocs", "stickarena", "mapEditorTiles.csv")
    raw = open(csv_path, encoding="latin-1").read().replace("&mapEditorTileData=", "")
    rows = [r for r in re.split(r"[\r\n]+", raw)
            if r.strip() and not r.startswith("Tile Name")]
    per_set = {}
    collision = {}
    for r in rows:
        p = r.split(",")
        if len(p) < 4:
            continue
        name, rot, mir, col = p[0], int(p[1]), int(p[2]), int(p[3])
        m = re.match(r"_(\d)([A-Z])(\d+)$", name)
        if not m:
            continue
        per_set[m.group(1)] = per_set.get(m.group(1), 0) + 1
        collision[col] = collision.get(col, 0) + 1

    by_export = {}
    for cid, v in chars.items():
        for n in v.get("export_names", []):
            by_export.setdefault(n, int(cid))

    shapes = []
    for t in range(10):
        cid = by_export.get("tileCol%d" % t)
        rec = OrderedDict([("collision_type", t), ("character_id", cid)])
        svg = sprite_svg(cid) if cid else None
        if svg:
            s = open(svg, encoding="utf-8").read()
            w = re.search(r'width="([\d.]+)px"', s)
            h = re.search(r'height="([\d.]+)px"', s)
            rec["width_px"] = float(w.group(1)) if w else None
            rec["height_px"] = float(h.group(1)) if h else None
            rec["svg"] = os.path.relpath(svg, REF).replace("\\", "/")
            rec["blocks_bullets"] = t == 3      # qxTtuh() checks == 3
        shapes.append(rec)

    return OrderedDict([
        ("tile_cell_px", 50),
        ("editor_tile_rows", len(rows)),
        ("tiles_per_set", dict(sorted(per_set.items()))),
        ("collision_type_histogram", dict(sorted(collision.items()))),
        ("collision_shapes", shapes),
        ("note", "Collision type is the 6th character of each 6-char tile cell "
                 "in a .dat file; the client attaches 'tileCol<type>' and "
                 "hit-tests it (frame_1/DoAction.as:496, reloadTile)."),
    ])


def sprite_svg(cid):
    """Path of the first rendered frame of a sprite, by original id."""
    prefix = "DefineSprite_%d" % cid
    if not os.path.isdir(SPR):
        return None
    for d in os.listdir(SPR):
        if d == prefix or d.startswith(prefix + "_"):
            p = os.path.join(SPR, d, "1.svg")
            if os.path.exists(p):
                return p
    return None


def sprite_dir(cid):
    prefix = "DefineSprite_%d" % cid
    if not os.path.isdir(SPR):
        return None
    for d in sorted(os.listdir(SPR)):
        if d == prefix or d.startswith(prefix + "_"):
            return d
    return None


# ---------------------------------------------------------------------------
# 5. Constants, each verified against the line it is quoted from
# ---------------------------------------------------------------------------
CONSTANTS = [
    # physics / player
    ("friction", 0.65, "velocity multiplier per frame", "frame_1/DoAction.as", 8502,
     "var friction = 0.65;"),
    ("walkAccel", 3, "px/frame^2 (player.lqkTiW, from sPlayerAcc)", "frame_1/DoAction.as", 2874,
     "this.lqkTiW = 3;"),
    ("maxVel", 9, "px/frame (player.maxVel, from sPlayerMaxVel)", "frame_1/DoAction.as", 2875,
     "this.maxVel = 9;"),
    ("walkSpeedMultiplier", 0.7, "W-key multiplier (player.qkKZwi)", "frame_1/DoAction.as", 2876,
     "this.qkKZwi = 0.7;"),
    ("rotationSpeed", 1.5, "smoothRot divisor (player.rotVel)", "frame_1/DoAction.as", 2877,
     "this.rotVel = 1.5;"),
    ("playerMaxHP", 60, "vwcSqZ / qxCihK", "frame_1/DoAction.as", 2864,
     "this.vwcSqZ = this.qxCihK = 60;"),
    ("deadRespawnFrames", 150, "kkPTHf / kkEEBi, 1 per frame", "frame_1/DoAction.as", 2886,
     "this.kkEEBi = this.kkPTHf = 150;"),
    ("spawnInvulnFrames", 133.3, "zqbcal / lqmKIZ, 1 per frame", "frame_1/DoAction.as", 2887,
     "this.lqmKIZ = this.zqbcal = 133.3;"),
    ("weaponPickupShortensInvuln", 66.6, "zqbcal -= 66.6 on pickup", "frame_1/DoAction.as", 9212,
     "this.zqbcal -= 66.6;"),
    # combat geometry
    ("meleeRangeSq", 10000, "distance^2 gate for non-ranged weapons", "frame_1/DoAction.as", 4119,
     "if(weapons[w].range || distance < 10000)"),
    ("maxAttackRangeSq", 250000, "distance^2 gate for any hit", "frame_1/DoAction.as", 4117,
     "if(distance < 250000)"),
    ("hitProbeOffset", 6, "px, hitTest probe at +/-6", "frame_1/DoAction.as", 4121,
     "hitTest(xx - 6,yy - 6,true)"),
    ("projectileStep", 10, "px per raycast step", "frame_1/DoAction.as", 4128,
     "var hitDistance = resolution = 10;"),
    ("gunLength", 30, "px, raycast starts at attacker + 30", "frame_1/DoAction.as", 4129,
     "var gunLength = 30;"),
    ("attackCooldownMsPerUnit", 33, "kkwrFk = qxdMlq * 33", "frame_1/DoAction.as", 9250,
     "this.kkwrFk = weapons[this.qkUfJI].qxdMlq * 33;"),
    # world
    ("tilePx", 50, "tile cell size", "frame_1/DoAction.as", 4134,
     "/ 50 + 0.5);"),
    ("tileWindowCols", 13, "reloadTile modulo", "frame_1/DoAction.as", 487,
     "while(tX > 12)"),
    ("tileWindowRows", 10, "reloadTile modulo", "frame_1/DoAction.as", 492,
     "while(tY > 9)"),
    ("cameraLeft", 250, "scroll when player x < 250 (zqZLsy)", "frame_1/DoAction.as", 2894,
     "this.zqZLsy = 250;"),
    ("cameraRight", 300, "scroll when player x > 300 (kkjecK)", "frame_1/DoAction.as", 2895,
     "this.kkjecK = 300;"),
    ("cameraTop", 175, "scroll when player y < 175 (qxOLFJ)", "frame_1/DoAction.as", 2896,
     "this.qxOLFJ = 175;"),
    ("cameraBottom", 225, "scroll when player y > 225 (lqbwJm)", "frame_1/DoAction.as", 2897,
     "this.lqbwJm = 225;"),
    # movement classification
    ("velocityDeadzone", 0.2, "|v| below this snaps to 0", "frame_1/DoAction.as", 6036,
     "if(Math.abs(xVel) < 0.2)"),
    ("standThreshold", 0.8, "|v| below this -> stand", "frame_1/DoAction.as", 6045,
     "if(vel < 0.8)"),
    ("collisionBounce", -0.5, "velocity multiplier on hit", "frame_1/DoAction.as", 6008,
     "xVel *= -0.5;"),
    # animation
    ("walkLegCycle", 40, "legs frames while walking", "frame_1/DoAction.as", 6071,
     "if(int(f) > 40)"),
    ("runLegCycle", 18, "legs frames while running", "frame_1/DoAction.as", 6094,
     "if(int(f) > 18)"),
    ("walkAnimStep", 3.5, "f += vel / 3.5", "frame_1/DoAction.as", 6070,
     "f += vel / 3.5;"),
    ("runAnimStep", 9, "f += vel / 9", "frame_1/DoAction.as", 6093,
     "f += vel / 9;"),
    ("spawnFlickerAlphaStep", 25, "invulnerable alpha pulse", "frame_1/DoAction.as", 6132,
     "_alpha += 25;"),
    # networking
    ("userIDLength", 3, "IDLEN", "frame_1/DoAction.as", 8384,
     "var IDLEN = 3;"),
    ("positionScale", 10, "x/y are sent *10", "frame_1/DoAction.as", 8961,
     "- xqXvQHh._x) * 10);"),
    ("velocityScale", 1000, "velocities are sent *1000", "frame_1/DoAction.as", 8968,
     "this.yVel * 1000"),
    ("remotePredictionOffsetFrames", 3, "approximateFrameDelay = ping/33 + 3", "frame_1/DoAction.as", 4384,
     "remoteAvgPing / 33 + 3"),
    # round
    ("roundSummarySeconds", 11, "sSummaryTime", "frame_1/DoAction.as", 3402,
     "tqmQZc = int(this.sSummaryTime);"),
    ("roundAdSeconds", 20, "sAdTime", "frame_1/DoAction.as", 3403,
     "qxIYpT = int(this.sAdTime);"),
    ("serverRoundTimeOffset", 31, "server sends roundTime + 31 = summary + ad", "ballistickemu/src/ballistickemu/Tools/StickPacketMaker.java", 101,
     "RoundTime + 31"),
    ("scorePackingBase", 13, "score = (lqexbO - 11) / 13", "frame_1/DoAction.as", 9056,
     "(this.lqexbO - 11) / 13"),
    ("deathPackingBase", 11, "deaths = (jhSfVJ - 13) / 11", "frame_1/DoAction.as", 9065,
     "(this.jhSfVJ - 13) / 11"),
]


def parse_constants():
    out = []
    for name, value, unit, rel, line, expect in CONSTANTS:
        path = os.path.join(REF, "extracted", "scripts", "as", rel) \
            if rel.startswith("frame") else os.path.join(REPO, rel)
        if not os.path.exists(path):
            fail("source missing for constant %s: %s" % (name, path))
        lines = read_lines(path)
        if line < 1 or line > len(lines):
            fail("line %d out of range for %s" % (line, rel))
        actual = lines[line - 1]
        if expect not in actual:
            fail("constant %s: expected %r at %s:%d, found %r"
                 % (name, expect, rel, line, actual.strip()))
        out.append(OrderedDict([
            ("name", name), ("value", value), ("unit", unit),
            ("source", "%s:%d" % (rel, line)),
            ("source_text", actual.strip()),
        ]))
    return out


# ---------------------------------------------------------------------------
# 6. System -> evidence map
# ---------------------------------------------------------------------------
def script_ref(relpath, lines, what):
    """Reference a script line range and verify it exists.

    Validating here is what keeps the index honest: a range that points past the
    end of a file (or at a file that is not there) aborts the build.
    """
    path = os.path.join(AS, relpath)
    if not os.path.exists(path):
        fail("script_ref: missing file %s" % relpath)
    total = len(read_lines(path))
    m = re.match(r"^(\d+)-(\d+)$", str(lines))
    if not m:
        fail("script_ref: bad line range %r for %s" % (lines, relpath))
    a, b = int(m.group(1)), int(m.group(2))
    if a < 1 or b < a or b > total:
        fail("script_ref: range %s out of bounds for %s (%d lines)"
             % (lines, relpath, total))
    return OrderedDict([("script", relpath), ("lines", lines), ("what", what)])


def build_systems(chars, weapons, anim, tiles):
    W = {w["id"]: w for w in weapons}

    def sym(cid, role):
        c = chars.get(str(cid))
        if c is None:
            fail("unknown character id %s (%s)" % (cid, role))
        return OrderedDict([
            ("id", cid),
            ("role", role),
            ("export_names", c.get("export_names", [])),
            ("frames", c.get("declared_frame_count")),
            ("frame_labels", [l["name"] for l in c.get("frame_labels", [])][:12]),
            ("sprite_dir", sprite_dir(cid)),
        ])

    systems = []

    systems.append(OrderedDict([
        ("id", "player"),
        ("title", "Player construction, dimensions and animation"),
        ("summary",
         "A player is an instance of the library symbol characterMC (id 3268), "
         "attached at runtime with attachMovie. Its body clip fqBEfG holds the "
         "stick figure and a 3-frame state timeline (idle/walk/run) whose legs "
         "sub-clip advances with speed; the arm/weapon clip gfoKHPq holds a "
         "49-frame table of per-weapon idle/run/attack poses."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "2851-2899", "stick() constructor: all player state and defaults"),
            script_ref("frame_1/DoAction.as", "3845-3886", "addPlayer(): attachMovie('characterMC', ...) and id assignment"),
            script_ref("frame_1/DoAction.as", "6055-6172", "animatePlayer(): body/legs/arm state machine"),
            script_ref("frame_1/DoAction.as", "1091-1095", "getTargetRotation(facing)"),
            script_ref("frame_1/DoAction.as", "1061-1086", "smoothRot(): rotation interpolation"),
            script_ref("frame_1/DoAction.as", "4305-4345", "changePlayerWeapon() / changePlayerColor()"),
            script_ref("frame_1/DoAction.as", "4497-4508", "updateLocalPlayerSpinnerAndPet()"),
        ]),
        ("symbols", [
            sym(3268, "characterMC - player rig root (runtime-attached)"),
            sym(1767, "fqBEfG - body: 3 frames idle/walk/run"),
            sym(972, "legs - idle legs"),
            sym(2530, "gfoKHPq - arm/weapon clip, 49 labelled frames"),
            sym(3032, "gfyeOfn - spawn/ghost body (hidden on spawnDone)"),
            sym(3249, "deathMC - death overlay"),
            sym(3076, "dieMC - death animation"),
            sym(3017, "soulHellMC - death soul effect"),
            sym(3257, "soulHeavenMC - spawn soul effect"),
            sym(3267, "textMC - name/id/ping text container"),
        ]),
        ("animation", anim),
        ("constants", ["playerMaxHP", "spawnInvulnFrames", "deadRespawnFrames",
                       "walkLegCycle", "runLegCycle", "walkAnimStep", "runAnimStep",
                       "rotationSpeed", "spawnFlickerAlphaStep"]),
        ("server", [
            "ballistickemu/src/ballistickemu/Lobby/handlers/LoginHandler.java:99-130 "
            "(name padded to 20, colour, stats)",
            "ballistickemu/src/ballistickemu/Tools/StickPacketMaker.java:187 "
            "(getClientInfo: uid, name, colour, kills, deaths, wins, losses, rounds, pass, level)",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "movement-collision"),
        ("title", "Movement, acceleration and tile collision"),
        ("summary",
         "Movement is a per-frame velocity integration with acceleration toward a "
         "per-weapon max speed, friction 0.65, and an 8-way facing encoded as a "
         "2-character string ('1'=up/left, '2'=down/right, '0'=none). Collision is "
         "not a tile solver: the client hit-tests the player against a movieclip "
         "layer that holds a tileCol<type> shape per visible tile, and reflects "
         "velocity by -0.5 on contact. The camera scrolls when the player leaves a "
         "250..300 x 175..225 dead zone, and the world is a 13x10 tile window that "
         "is re-populated as the camera moves."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "5944-6002", "ygsfeyb(): acceleration, diagonal normalisation, friction"),
            script_ref("frame_1/DoAction.as", "6002-6034", "jhzeUQ(): per-axis collision probe, velocity reflection"),
            script_ref("frame_1/DoAction.as", "6034-6055", "ehbdybe(): deadzone + walk/stand classification"),
            script_ref("frame_1/DoAction.as", "9286-9494", "stick.prototype.move(): input, facing, camera, scroll, timers"),
            script_ref("frame_1/DoAction.as", "484-532", "reloadTile(): 13x10 window slot mapping and tileCol attach"),
            script_ref("frame_1/DoAction.as", "532-699", "updateEarth()/updateEarthCol()/updateEarthRow(): window scrolling"),
            script_ref("frame_1/DoAction.as", "699-736", "moveToCoords()"),
        ]),
        ("symbols", [sym(5025 + 0, "tileCol0 - empty (no collision)"),
                     sym(7475, "tileCol1 - full tile, 52 x 51.1"),
                     sym(5034, "tileCol3 - full tile, blocks bullets"),
                     sym(5032, "tileCol4 - full tile, map border")]),
        ("tiles", tiles),
        ("constants", ["friction", "walkAccel", "maxVel", "walkSpeedMultiplier",
                       "velocityDeadzone", "standThreshold", "collisionBounce",
                       "tilePx", "tileWindowCols", "tileWindowRows",
                       "cameraLeft", "cameraRight", "cameraTop", "cameraBottom"]),
        ("server", [
            "The server does not simulate movement: GamePacketBroadcastHandler.java:30 "
            "re-broadcasts opcode 1/2/4/5/6/8 verbatim.",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "weapons"),
        ("title", "Weapons, pickups, attacks and damage"),
        ("summary",
         "14 weapon slots (0-13) are declared in initializeWeapons() as "
         "weaponType records. Melee weapons hit-test a hit area at <=100 px; ranged "
         "weapons raycast in 10 px steps and are blocked by collision type 3. "
         "Hit resolution is victim-side: the attacker broadcasts opcode 4, every "
         "other client checks whether that attack hits its own player, and the "
         "victim applies the damage locally and broadcasts opcode 6. Map weapon "
         "spawns respawn after the map's per-spawn delay, and picking a weapon "
         "shortens spawn protection by 66.6 frames."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "1823-1861", "initializeWeapons(): the 14-entry table"),
            script_ref("frame_1/DoAction.as", "1841-1861", "weaponType(): record layout"),
            script_ref("frame_1/DoAction.as", "4098-4160", "qxTtuh(): range gates, hitTest probes, projectile raycast"),
            script_ref("frame_1/DoAction.as", "6172-6260", "updateWeaponSpawns()/spawnWeapon()/animateWeaponPickups()"),
            script_ref("frame_1/DoAction.as", "9208-9264", "qxCsEe(): weapon switch, pickup, invuln shortening"),
            script_ref("frame_1/DoAction.as", "9230-9264", "qkZPDc(): attack trigger, cooldown, particles"),
            script_ref("frame_1/DoAction.as", "9264-9286", "autoAttack(): hold-to-fire vs click-per-shot"),
            script_ref("frame_9/PlaceObject2_236_241/CLIPACTIONRECORD onClipEvent(mouseUp).as", "1-4",
                       "mouseUp sets zqyafO=true -> semi-auto weapons re-arm"),
        ]),
        ("weapons", weapons),
        ("animation", anim),
        ("symbols", [
            sym(4343, "pickupswordMC"), sym(4344, "pickupsledgeMC"),
            sym(4345, "pickupshotgunMC"), sym(4348, "pickupglockMC"),
            sym(4350, "pickupfistMC"), sym(4351, "pickupbatMC"),
            sym(4352, "pickupak47MC"), sym(6209, "pickupchaingunMC"),
            sym(6210, "pickupchainsawMC"), sym(6211, "pickupflamethrowerMC"),
            sym(6212, "pickuplaserswordMC"), sym(6213, "pickuprailgunMC"),
            sym(6214, "pickuphelmetMC"),
            sym(4356, "sledgeParticleMC"), sym(4357, "shotgunParticleMC"),
            sym(4358, "glockParticleMC"), sym(4361, "ak47ParticleMC"),
            sym(5652, "railgunParticleMC"), sym(6402, "railgunParticleLowMC"),
            sym(4374, "bloodSword0MC"), sym(4387, "bloodShotgun2MC"),
            sym(4414, "bloodBullet2MC"), sym(4450, "bloodBat1MC"),
        ]),
        ("sounds", None),
        ("constants", ["meleeRangeSq", "maxAttackRangeSq", "hitProbeOffset",
                       "projectileStep", "gunLength", "attackCooldownMsPerUnit",
                       "weaponPickupShortensInvuln"]),
        ("server", [
            "Game/handlers/GamePacketBroadcastHandler.java:30 relays attack/damage packets",
            "Game/handlers/KillHandler.java handles opcode 7 (kill confirmation)",
            "Lobby/handlers/BuyItemRequestHandler.java + Types/StickShop.java own shop items, "
            "not in-match weapons",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "maps"),
        ("title", "Maps, tile sets and map objects"),
        ("summary",
         "A map is a plain-text record file: inf=<cols> <rows> <name>, a grid of "
         "6-character tile cells (graphic id, rotation, mirror, collision type), "
         "8 player spawns, 8 weapon spawns (x, y, weapon id, delay) and a tile set "
         "index. The editor serialises exactly this format in generateMapString(). "
         "Stock maps come from maps/558/<name>; custom maps come from api.php."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "6308-6390", "loadStockOrCustomArea()/loadCustomArea()/loadStockArea()"),
            script_ref("frame_1/DoAction.as", "6390-6474", "loadArea(): metadata, tile grid, spawns, round time, tile set"),
            script_ref("frame_1/DoAction.as", "6474-6491", "unloadArea()"),
            script_ref("frame_6/DoAction.as", "223-269", "generateMapString(): exact .dat serialiser"),
            script_ref("frame_6/DoAction.as", "181-223", "performSaveEditor(): api.php maps.save"),
            script_ref("frame_6/DoAction.as", "432-624", "pressNewMapOK(): width/height/theme validation"),
        ]),
        ("tiles", tiles),
        ("symbols", [
            sym(5754, "tile3A6 - example set-3 tile graphic"),
            sym(4139, "tile2K1 - example set-2 tile graphic"),
            sym(3399, "parallaxBG4 - background used when tileSet >= 4"),
            sym(6243, "tileSetsMC - editor tile palette"),
        ]),
        ("constants", ["tilePx"]),
        ("server", [
            "htdocs/stickarena/api.php: method=xgen.stickarena.maps.list/get/save (table `maps`)",
            "Lobby/handlers/MapCycleRequestHandler.java, Game/handlers/SetMapCycleListHandler.java",
            "Game/handlers/MapRatingHandler.java (opcode 0i)",
            "Types/StickRoom.java:45-62 (MapID, CycleMode, MapCycleList, RoundTime)",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "health-death-scoring"),
        ("title", "Health, death, respawn and scoring"),
        ("summary",
         "Each player has 60 HP. Damage is an integer subtraction with a HP-bar mask "
         "animation; at <=0 the player enters 'dead', plays deathFX, increments "
         "deaths, and auto-respawns after 150 frames at a random map spawn point "
         "with 133.3 frames of invulnerability. Kills and deaths are packed into "
         "two integers (score*13+11 and deaths*11+13) so the client can ship them "
         "as compact decimals. Round end awards wins/losses by leaderboard position."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "9074-9127", "stick.prototype.damage()"),
            script_ref("frame_1/DoAction.as", "9127-9159", "tqkYQT(): death transition"),
            script_ref("frame_1/DoAction.as", "9159-9201", "stick.prototype.spawn()"),
            script_ref("frame_1/DoAction.as", "9047-9074", "addToScore/getScore/addToDeaths/getDeaths/updateHPBar"),
            script_ref("frame_1/DoAction.as", "5838-5859", "getPosition(): leaderboard ranking"),
            script_ref("frame_1/DoAction.as", "5058-5090", "vzvxUc(): kill broadcast handling"),
            script_ref("frame_1/DoAction.as", "7000-7049", "endRound(): wins/losses, summary"),
            script_ref("frame_1/DoAction.as", "7049-7091", "startNextRound(): map cycle rotation, round time"),
            script_ref("frame_1/DoAction.as", "3104-3138", "updateRoundTimer()"),
        ]),
        ("symbols", [sym(5037, "deathFX - local death effect"),
                     sym(5036, "remoteDeathFX - remote death effect"),
                     sym(5039, "spawnFX - local spawn effect"),
                     sym(5038, "remoteSpawnFX - remote spawn effect")]),
        ("constants", ["playerMaxHP", "deadRespawnFrames", "spawnInvulnFrames",
                       "scorePackingBase", "deathPackingBase",
                       "roundSummarySeconds", "roundAdSeconds", "serverRoundTimeOffset"]),
        ("server", [
            "Types/StickRoom.java:256-266 (1 s round timer, RoundTime 300, reset at -30)",
            "Types/StickRoom.java:288-330 (getWinner by most kills)",
            "Game/handlers/KillHandler.java (opcode 7)",
            "htdocs/stickarena/stick_arena.php action=round_stats (kills/deaths/rounds/wins/losses)",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "multiplayer-sync"),
        ("title", "Multiplayer synchronisation"),
        ("summary",
         "The socket carries null-terminated text. The client sends opcode 1 "
         "(position/state) at most every minSendTime ms, plus event packets 4/5/6/7/8; "
         "the server relays them to the room. Remote players are reconstructed by "
         "re-running the same movement integrator for ping/33+3 frames from the last "
         "packet, then lerping with remoteSmoothing=8. The server is a relay, not an "
         "authority: it never simulates movement, damage or hits."),
        ("scripts", [
            script_ref("frame_1/DoAction.as", "8942-9030", "stick.prototype.send*: every outbound packet"),
            script_ref("frame_1/DoAction.as", "4824-4914", "socketCalls(): inbound M-packet dispatch"),
            script_ref("frame_1/DoAction.as", "4345-4419", "updatePlayer(): remote state + prediction"),
            script_ref("frame_1/DoAction.as", "4453-4491", "remotePlayerPrediction()"),
            script_ref("frame_1/DoAction.as", "3775-3803", "updateGameState(): U packet decode"),
            script_ref("frame_1/DoAction.as", "8809-8925", "XMLSocket.prototype.onData: first-char dispatch"),
            script_ref("frame_9/PlaceObject2_236_241/CLIPACTIONRECORD onClipEvent(enterFrame).as", "1-3",
                       "the per-frame tick: _parent.onFrame('main')"),
            script_ref("frame_1/DoAction.as", "2927-2967", "onFrame(): send cadence, move, autoAttack"),
        ]),
        ("constants", ["userIDLength", "positionScale", "velocityScale",
                       "remotePredictionOffsetFrames", "friction"]),
        ("settings", ["sMinSendTime", "sMinSendTimeCompat", "sKeepAliveTime",
                      "sPingAvgPeriod", "sRemoteSmoothing", "sRemoteRotSmoothing",
                      "sMaxMsgLen", "sMaxMsgLenLobby"]),
        ("server", [
            "Tools/StickNetworkHandler.java:58-96 (null-delimited text, lobby/game split)",
            "Game/PacketHandlerGame.java:116-120 (relay of 1/2/4/5/6/8)",
            "Tools/StickPacketMaker.java:122-130 (getBroadcastPacket)",
        ]),
    ]))

    systems.append(OrderedDict([
        ("id", "lobby-ui-social"),
        ("title", "Lobby, UI and social features"),
        ("summary",
         "The lobby is main-timeline frame 3 (lobbyFrame) with room list, user list, "
         "chat, private messages, VIP list and create/join dialogs. Chat is filtered "
         "by com/languagefilter.ini, length-limited and rate-limited per sender. "
         "Social systems include ignore list, find-player, vote kick, moderator "
         "warn/ban/global message, and a highscore link."),
        ("scripts", [
            script_ref("frame_3/DoAction.as", "1-53", "lobbyInitializeComponents()"),
            script_ref("frame_3/DoAction.as", "132-268", "lobbySelectArena()/lobbyDisplayRoomDetail()"),
            script_ref("frame_3/DoAction.as", "382-449", "VIP list add/remove"),
            script_ref("frame_3/DoAction.as", "745-808", "pressCreateGameOK(): room creation and map-cycle options"),
            script_ref("frame_1/DoAction.as", "4935-5037", "remoteChatMsg()/remoteChatMsgLobby(): ignore, filter, limits"),
            script_ref("frame_1/DoAction.as", "5810-5834", "sendPrivateMessage()"),
            script_ref("frame_1/DoAction.as", "5037-5058", "vwPzUs(): vote-kick tally"),
            script_ref("frame_1/DoAction.as", "7995-8038", "ignoreUser()"),
            script_ref("frame_1/DoAction.as", "7655-7995", "processSlashSyntaxCommand()"),
        ]),
        ("symbols", [sym(5179, "window304JoinPrivateMessageMC"),
                     sym(5182, "window304CreateGameMessageMC"),
                     sym(6651, "roomBallistickLobbyMC"),
                     sym(6652, "roomNormalLobbyMC")]),
        ("settings", ["sMaxMsgLen", "sMaxMsgLenLobby", "sMaxLobbyMsgs", "sMinChatSendMS",
                      "sVoteKickDisplayTime", "sVoteKickDisabledTime", "sMaxNumPlayersLobby"]),
        ("server", [
            "Lobby/PacketHandlerLobby.java (0x opcode table)",
            "Lobby/handlers/GeneralChatHandler.java",
            "Lobby/handlers/FindRequestHandler.java, ModWarnHandler.java, ModBanHandler.java, "
            "ModBanNameHandler.java, ModGlobalHandler.java",
            "Game/handlers/VoteKickHandler.java, Types/StickRoom.java:225-243 (kick tally)",
            "htdocs/stickarena/stickarena/highscore.php",
        ]),
    ]))

    return systems


# ---------------------------------------------------------------------------
# 7. HTML contact sheets
# ---------------------------------------------------------------------------
def rel_from_vis(path):
    return os.path.relpath(path, VIS).replace("\\", "/")


def img_card(cid, label, chars):
    d = sprite_dir(cid)
    if not d:
        return None
    p = os.path.join(SPR, d, "1.svg")
    if not os.path.exists(p):
        return None
    c = chars.get(str(cid), {})
    frames = c.get("declared_frame_count")
    names = ", ".join(c.get("export_names", [])[:2])
    return ('<figure><a href="%s"><img src="%s" alt="%s"></a>'
            '<figcaption><b>%d</b> %s<br><small>%s%s</small></figcaption></figure>'
            % (rel_from_vis(p), rel_from_vis(p), html.escape(label),
               cid, html.escape(label),
               html.escape(names or "(no export name)"),
               ", %s frames" % frames if frames else ""))


def build_html(chars, weapons, anim, tiles):
    os.makedirs(VIS, exist_ok=True)
    parts = ['<!doctype html><meta charset="utf-8"><title>sab558 visual index</title>',
             '<style>',
             'body{background:#14161a;color:#d8dee9;font:14px/1.5 system-ui,sans-serif;margin:24px}',
             'h1{font-size:20px}h2{font-size:16px;margin-top:36px;border-bottom:1px solid #2d333b;padding-bottom:6px}',
             'h3{font-size:14px;color:#9aa7b8;margin:18px 0 6px}',
             '.grid{display:flex;flex-wrap:wrap;gap:10px}',
             'figure{margin:0;background:#1c2027;border:1px solid #2d333b;border-radius:6px;padding:6px;width:150px;text-align:center}',
             'figure img{max-width:138px;max-height:120px;background:#0b0d10;display:block;margin:0 auto}',
             'figcaption{font-size:11px;color:#9aa7b8;margin-top:4px;word-break:break-word}',
             'table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #2d333b;padding:3px 6px;text-align:left}',
             'a{color:#8ab4f8}code{color:#a5d6a7}',
             '</style>',
             '<h1>sab558 visual index</h1>',
             '<p>Generated by <code>scripts/build_systems_index.py</code> from the '
             'existing extraction. Images link to the original SVG/PNG files in '
             '<code>extracted/</code>; nothing is re-exported here.</p>']

    # player rig
    parts.append('<h2>Player rig — characterMC (3268)</h2><div class="grid">')
    for cid, label in [(3268, "characterMC"), (1767, "fqBEfG body"),
                       (972, "legs"), (2530, "gfoKHPq arm/weapon"),
                       (3032, "gfyeOfn spawn ghost"), (3249, "deathMC"),
                       (3076, "dieMC"), (3017, "soulHellMC"), (3257, "soulHeavenMC"),
                       (3267, "textMC")]:
        card = img_card(cid, label, chars)
        if card:
            parts.append(card)
    parts.append('</div>')

    # weapons
    parts.append('<h2>Weapons</h2>')
    parts.append('<table><tr><th>id</th><th>name</th><th>anim</th><th>damage</th>'
                 '<th>range</th><th>cooldown units</th><th>walk speed</th>'
                 '<th>auto</th></tr>')
    for w in weapons:
        parts.append('<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                     '<td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (w["id"], html.escape(str(w.get("attackAnim"))),
                        html.escape(str(w.get("idleAnim"))), w.get("damage"),
                        "ranged" if w.get("range") else "melee",
                        w.get("qxdMlq"), w.get("walkingSpeed"),
                        "yes" if w.get("automatic") else "no"))
    parts.append('</table>')

    parts.append('<h2>Weapon animations — gfoKHPq (2530)</h2>')
    by_label = {a["label"]: a for a in anim}
    for w in weapons:
        parts.append('<h3>%d — %s</h3><div class="grid">' % (w["id"], html.escape(str(w.get("attackAnim")))))
        for suffix, key in (("Idle", "idleAnim"), ("RunIdle", "runAnim")):
            lab = str(w.get(key, "")) + suffix
            a = by_label.get(lab)
            if a and a["clip_character_id"]:
                card = img_card(a["clip_character_id"], lab, chars)
                if card:
                    parts.append(card)
        for rnd in (1, 2, 3):
            lab = str(w.get("attackAnim", "")) + "Attack%d" % rnd
            a = by_label.get(lab)
            if a and a["clip_character_id"]:
                card = img_card(a["clip_character_id"], lab, chars)
                if card:
                    parts.append(card)
        parts.append('</div>')

    # collision shapes
    parts.append('<h2>Tile collision shapes — tileCol0..9</h2><div class="grid">')
    for s in tiles["collision_shapes"]:
        if s.get("character_id"):
            card = img_card(s["character_id"],
                            "Col%d %sx%s" % (s["collision_type"],
                                             s.get("width_px"), s.get("height_px")), chars)
            if card:
                parts.append(card)
    parts.append('</div>')

    # tile sets: first exported tile of each set
    parts.append('<h2>Tile graphics — one per set</h2><div class="grid">')
    by_export = {}
    for cid, v in chars.items():
        for n in v.get("export_names", []):
            by_export.setdefault(n, int(cid))
    for s in "012345":
        for n in sorted(by_export):
            if re.match(r"^tile%s[A-Z]0$" % s, n):
                card = img_card(by_export[n], n, chars)
                if card:
                    parts.append(card)
                break
    parts.append('</div>')

    # fx
    parts.append('<h2>Combat / spawn effects</h2><div class="grid">')
    for cid, label in [(5035, "fadeInFX"), (5037, "deathFX"), (5038, "remoteSpawnFX"),
                       (5039, "spawnFX"), (5040, "localDamageFX"), (61, "damageFX"),
                       (12, "damageHpFX"), (43, "shakeSAFX"), (5, "fadeFX")]:
        card = img_card(cid, label, chars)
        if card:
            parts.append(card)
    parts.append('</div>')

    # ui windows
    parts.append('<h2>UI windows (window*MC)</h2><div class="grid">')
    count = 0
    for cid, v in sorted(chars.items(), key=lambda kv: int(kv[0])):
        for n in v.get("export_names", []):
            if n.startswith("window") and count < 60:
                card = img_card(int(cid), n, chars)
                if card:
                    parts.append(card)
                    count += 1
                break
    parts.append('</div>')

    out = os.path.join(VIS, "index.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(parts) + "\n")
    return out


# ---------------------------------------------------------------------------
def main():
    os.makedirs(SYS, exist_ok=True)
    chars = load(os.path.join(MAN, "characters.json"))["characters"]
    edges = load(os.path.join(MAN, "relationships.json"))["edges"]
    manifest = load(os.path.join(MAN, "export_manifest.json"))
    settings = load(os.path.join(ANA, "settings558b.json"))["sections"]

    weapons, wparams, num = parse_weapons()
    clip_root, anim = parse_weapon_animations(chars, edges)
    weapons = annotate_weapons(weapons, anim)
    sounds, missing_sounds = parse_sounds(chars, manifest)
    tiles = parse_tiles(chars)
    constants = parse_constants()

    settings_flat = {}
    for sec, kv in settings.items():
        for k, v in kv.items():
            settings_flat[k] = v

    def write(name, obj):
        with open(os.path.join(SYS, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")

    write("weapons.json", OrderedDict([
        ("source", "extracted/scripts/as/frame_1/DoAction.as initializeWeapons() / weaponType()"),
        ("constructor_parameters", wparams),
        ("numWeapons", num),
        ("note", "Field names come from the weaponType() constructor. "
                 "cooldown_ms / damage_per_second / attack_variants_in_animation_table "
                 "are derived and cross-checked against the gfoKHPq label table."),
        ("weapons", weapons),
    ]))
    write("animations.json", OrderedDict([
        ("root_character_id", clip_root),
        ("root_export_names", chars[str(clip_root)].get("export_names", [])),
        ("fps", 34),
        ("note", "Each label names a frame in gfoKHPq; the clip placed on that frame "
                 "is the animation that plays. Duration = clip frame count / 34 fps."),
        ("clips", anim),
    ]))
    write("sounds.json", OrderedDict([
        ("source", "attachSound() calls in extracted/scripts/as/frame_1/DoAction.as"),
        ("unresolved_export_names", missing_sounds),
        ("sounds", sounds),
    ]))
    write("tiles.json", tiles)
    write("constants.json", OrderedDict([
        ("note", "Every entry was re-read from the cited source line by the builder."),
        ("client_settings", OrderedDict(
            (k, settings_flat[k]) for k in sorted(settings_flat)
            if k.startswith(("sPlayer", "sScroll", "sRound", "sSummary", "sAd",
                             "sMinSend", "sKeepAlive", "sPing", "sRemote",
                             "sMaxMsg", "sMaxNum", "sMaxArena", "sCollision",
                             "sOption", "sVoteKick", "sMinChat", "sMaxPing",
                             "sMinFPS", "sServerTimeout", "sEnforce", "sDisplay",
                             "sEditor", "nMaxVIP", "nNumClassic", "nPass")))),
        ("code_constants", constants),
    ]))

    systems = build_systems(chars, weapons, anim, tiles)
    # attach sound evidence to the weapons system
    for s in systems:
        if s["id"] == "weapons":
            s["sounds"] = sounds
    write("semantic_index.json", OrderedDict([
        ("source_swf", load(os.path.join(MAN, "swf_header.json"))["path"]),
        ("source_swf_sha256", load(os.path.join(MAN, "swf_header.json"))["sha256"]),
        ("note", "System -> scripts / symbols / animations / sounds / settings / "
                 "server handlers. Script line ranges refer to "
                 "extracted/scripts/as/<script>. Symbol ids are original SWF ids."),
        ("systems", systems),
    ]))

    out = build_html(chars, weapons, anim, tiles)

    print("weapons parsed: %d (numWeapons=%d)" % (len(weapons), num))
    print("weapon animation clips: %d labels" % len(anim))
    print("sounds referenced: %d (unresolved: %d)" % (len(sounds), len(missing_sounds)))
    print("collision shapes: %d" % len(tiles["collision_shapes"]))
    print("constants verified against source: %d" % len(constants))
    print("systems indexed: %d" % len(systems))
    print("wrote %s" % os.path.relpath(SYS, REF))
    print("wrote %s" % os.path.relpath(out, REF))
    if missing_sounds:
        print("  unresolved sound names: %s" % ", ".join(missing_sounds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
