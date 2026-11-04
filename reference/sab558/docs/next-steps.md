# Recommended next steps

Ordered by value per unit of effort. Each item says what evidence would close it.

## 1. Close the map-encryption question (highest value, low effort)

`class.rc4crypt.php` exists in the web tier, `api.php` stores maps in
`maps.mapdata`, and `frame_1/DoAction.as:8307` holds a 16-character literal
`"Hx09TdCC62Nwln1P"`. The assumption that they belong together is untested.

- Trace the client's map save/load call in `extracted/scripts/as/frame_1/` and
  `frame_6/` (look for the `xgen.stickarena.maps.save` / `.get` literals).
- Confirm the RC4 key and the exact plaintext (XML? the `.dat` text?).
- Add a `docs/map-format.md` section with the confirmed answer, or record that
  the key is used for something else.

## 2. Reconcile the client/server opcode gaps

Confirmed mismatches (`docs/architecture.md` §8, `docs/protocol.md` §4):

| item | where |
| --- | --- |
| client sends `0e`, `0k`, `T` — server has no handler | `PacketHandlerLobby.java`, `PacketHandlerGame.java` |
| server sends error `42` and `5` — client handles only `0`–`4` | `recieveError`, `DoAction.as:5677` |

Since the client is a fixed binary, the practical fix is server-side: map the
client's `0e`/`0k` to `ModBanHandler`/`ModBanNameHandler`, implement or
explicitly reject `T`, and return error codes the client can display (use `2` or
`4` instead of `42`/`5`). Verify by replaying the packets against a local server
and watching both the server log and the client UI.

## 3. Build a protocol harness

There is currently no way to test the server without a Flash player.

- Write a small Python `socket` client that speaks the null-terminated protocol
  (`00`–`0m`, `1`–`9`, `K`, `T`) and records request/response pairs.
- Use it to produce a golden transcript per opcode, stored under
  `reference/sab558/analysis/protocol/`.
- This also gives the project its first automated test surface for the server.

## 4. Validate the map format across all 72 maps

`docs/architecture.md` §7 documents the format from one file
(`__xgenhq.dat`). Write a validator that checks, for every
`htdocs/stickarena/maps/558/**/*.dat`:

- `inf=<cols> <rows> <name>` present;
- exactly `cols*rows` tile tokens;
- `&sp=` pairs are even and inside the grid;
- `&ws=` groups of four;
- `&rt=` / `&ts=` present.

Emit `manifests/maps_558.json` with dimensions, tile counts and spawn counts per
map. That turns an observation into a verified property of the 558 map set.

## 5. Recover the missing XFL symbols (optional, medium effort)

FFDec's batch XFL export drops 1,723 sprites that no authored timeline places
(`docs/assets.md` §6). Worth testing: export those sprites individually with
`-selectid <id> -export xfl` into a scratch directory and see whether a
single-symbol XFL contains the symbol. If it does, the pipeline can merge them
into `extracted/xfl/LIBRARY/`.

## 6. Item / spinner / pet model

`settings558b.ini` (controls, map cycle, name pools), `upgradevalues558.ini`
(spinner costs) and the server's `shop` table plus `ItemType.java` describe the
same item space from three angles. Cross-reference them into one table:
item id → spinner/pet → price → colour slots. Confirmed by comparing
`analysis/upgradevalues558.json` with `Tools/ItemType.java` and the client's
`DefineSprite_<id>_petMC*` / `spinner*` symbols.

## 7. If animation reference is needed, prefer APNG over 24k SVGs

The opt-in `sprite_frames` stage produces 23,998 SVG files (~1.6 GB) because
every frame re-embeds the same bitmaps. `-format sprite:apng` produces one file
per sprite instead. Measure both, then pick one as the default for animation
review; keep the other as an option.

## 8. Pin the toolchain

`manifests/ffdec_version.txt` records `JPEXS Free Flash Decompiler v.26.4.0
nightly build 3604`. Nightly builds change output naming and formatting, so:

- record the `ffdec.jar` SHA-256 next to the version;
- fail the pipeline with a clear message if the version string differs from the
  recorded one (unless `--allow-other-ffdec` is passed).

## 9. Not recommended

- Do not "fix" the client SWF to match this server. The client is the primary
  source of truth for 558; the server is a reimplementation.
- Do not use `sab588.swf` or `dimensions.swf` to fill gaps. If 558 does not
  answer a question, the honest answer is "not determinable from 558 material".
