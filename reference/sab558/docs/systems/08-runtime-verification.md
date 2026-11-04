# 8. Runtime verification backlog

**Status (2026-11-04): items 1, 2, 3, 4, 7, 9 and 14 have been observed at runtime**
under Ruffle 0.7.1 against a local harness. Results, evidence paths and the
discrepancies they exposed are in
[09-runtime-evidence.md](09-runtime-evidence.md). Everything else below is still
open, and items that need the real Java server are called out explicitly.

No Adobe Flash Player runtime exists on this machine, so "runtime" here means
Ruffle (an emulator). Cases where that matters are marked inconclusive.

A test is "passed" when the observation matches the source claim; "failed" means
the source claim is wrong or incomplete and the doc must be corrected.

## 8.1 Priority order

| # | behaviour | why it matters | source claim to validate | status |
| --- | --- | --- | --- | --- |
| 1 | Effective movement speed and acceleration | The integrator consumes a *4-frame* delta every frame; every speed number in [02](02-movement-collision.md) is derived, not measured | `frame_1/DoAction.as:5944-6002`, `:1390-1396` | **verified** (4.94 / 2.24 px/frame) |
| 2 | Unresolved sound linkages | 4 case-mismatched names and 3 names with no symbol at all — some weapons may be silent | `:1924`, `:1937`, `:1941`, `:1975`, `:2007`, `:2082`, `:2084` | **partly verified** (3 of 7 silent); 4 case mismatches inconclusive |
| 3 | Victim-side damage authority | The whole combat model rests on "the victim decides it was hit" | `:4079`, `:4098-4160`, `:9074-9127` | **verified** — 12 dmg packets from victim, 60 HP, death, 4.38 s respawn |
| 4 | Self-echo of attack packets | The server echoes to the sender; the client must ignore its own attack | `:4079`, `StickRoom.java:89-110` | **verified** — attacker sent 0 damage packets; victim sent all 12 |
| 5 | Round timing contract | Client expects 300+11+20 s; server counts 300 → −1 → −30 | `:7064`, `:3104-3138`, `StickPacketMaker.java:101`, `StickRoom.java:259-265` | **partial** — clock is server-authoritative (verified); full 300 s duration not observed (§9.5) |
| 6 | Map `rt=` / `ts=` handling | Only 300/0 were ever shipped, so non-default values are unexercised | `:6399-6400`, `frame_6/DoAction.as:259-261` | open — needs a hand-edited custom map |
| 7 | Collision probe vs body art | A 12 px probe under a 24.3 px body should allow visual clipping | `:6002-6034` | **partial** — bounce verified (37 sign flips); visual clipping not assessed |
| 8 | Remote prediction under latency | Prediction re-simulates with the *local* physics and the local collision layer | `:4345-4419`, `:4453-4491` | open — needs two clients with induced latency |
| 9 | Error codes 42 and 5 | Client has no branch for them | `:5677-5785` | open — testable with the stub (it can send 42/5) |
| 10 | `0e` / `0k` / `T` opcodes | Client sends them; server has no handler | `:5800`, `:5808`, `:9029` | open — testable with the stub (it logs unhandled opcodes) |
| 11 | Vote-kick threshold | Server rule is `>1` and `>= clients-1` | `StickRoom.java:238` | open — enforcement needs the real server |
| 12 | Ghost / spectator mode | `collisionCheckGhost` and `ghostAlpha` change which position is authoritative | `:4102-4110`, `:6117-6152` | open |
| 13 | Spinner/pet colour rendering | Two-colour tint at alpha 75/100 with `setCustomObject2Colors` | `:4307-4343`, `:4497-4508` | open |
| 14 | Quickstart rooms | `!` prefix and generated names | `:4567-4573`, `:4583-4606` | **partially verified** (quickstart rooms observed) |

## 8.2 Test details

### 1. Movement speed

**Setup:** one client, `__xgenhq.dat` (flat areas), no weapon (fist), no lag.
**Method:** hold a direction for 3 s on flat ground; sample `xqXvQHh._x/_y` (or the
player clip) once per frame via the client's own debug HUD (`SYSINFO`).
**Expected from source:** run ≈ 4.9 px/frame ≈ 167 px/s; walk (W) ≈ 2.2 px/frame
≈ 75 px/s; sledge/ak47/shotgun/chaingun ≈ 3.4 px/frame ≈ 117 px/s.
**Record:** acceleration curve (px/frame²), terminal speed, and whether speed
changes when the frame rate drops (which would confirm the 4-frame delta bug).

### 2. Sound linkage failures

**Method:** equip each weapon and attack; listen for the attack and impact
sounds. For Ballistick weapons use a lab-pass account.
**Expected from source:**

| weapon | expected failure |
| --- | --- |
| shotgun | attack sound `shotgun00.wav` does not resolve (export is `Shotgun00.wav`) |
| ak47 | impact `ak47imp00.wav` vs `AK47imp00.wav` |
| sledge | impact `sledgeimp00.wav` vs `Sledgeimp00.wav` |
| sledge | pickup `Sledgepick00.wav` vs `sledgepick00.wav` |
| flamethrower | impact name has no symbol at all |
| railgun | impact name has no symbol at all |
| UI | `dragVolume.wav` (volume slider) has no symbol |

**Record:** which of these are silent. If a "failing" name still plays, Flash's
linkage lookup is case-insensitive and `docs/systems/03` §3.6 must be corrected.

### 3 & 4. Damage authority and self-echo

**Setup:** two clients, A and B, both in the same room; A attacks B.
**Method:** watch the packets (server log with `logchat`/debug) and the HP bars.
**Expected from source:** A sends `4`; the server echoes `M<A>4…` to both; only B
runs hit detection, B's HP drops locally, B sends `6`, and A's client shows only
blood/impact visuals for B.
**Also test:** A attacks empty air at point-blank against a wall — A must take no
damage from its own echo.
**Failure mode to look for:** B's HP drops on A's client (would mean attacker-side
damage), or A takes damage from its own attack.

### 5. Round timing

**Method:** create a room, start a round, and time: round start → `roundSummaryFrame`,
summary duration, and the moment the next map loads. Compare with the server log's
`RoundTime` countdown.
**Expected from source:** client ends the round at `roundTime + 11 + 20` = 331 s
from `startNextRound`, but re-syncs from `04` every >15 s of drift, so the server's
301 s should win. Observe which one actually ends the round.

### 6. Map `rt=` / `ts=`

**Method:** edit a copy of a map outside the repo (never the originals) to
`&rt= 120` and `&ts=4`, serve it as a custom map, and start a round.
**Expected from source:** `tqJqPc` starts at 120+31, the timer shows ~120 s, and
the background uses `parallaxBG4`.
**Note:** the editor always writes `rt=300`, so a custom map with another value
can only come from a hand-edited file or the API.

### 7. Collision probe

**Method:** walk the player into a wall at a shallow angle and screenshot.
**Expected from source:** the 12 × 12 probe stops the player with roughly 6 px of
body art inside the wall.
**Record:** whether tiles use collision type 1 (52 × 51.1) anywhere the player can
reach; only one editor tile uses it.

### 8. Prediction under latency

**Method:** two clients, 150–300 ms artificial latency on one; have the remote
player run into a corner and stop.
**Expected from source:** the remote body overshoots then blends back
(`remoteSmoothing = 8`), and the rotation lags (`remoteRotSmoothing = 4`).
**Watch for:** remote players passing through walls during prediction — the
predictor calls `jhzeUQ` against the *local* collision layer, which is valid only
because both clients loaded the same map.

### 9. Error codes

**Method:** (a) join a room that is full; (b) join a lab-pass room without a pass.
**Expected from source:** server sends `09` + `42`; client's `recieveError` has no
`42` branch, so no specific message appears. If a message *does* appear, find the
branch and update `docs/protocol.md` §4.

### 10. Unhandled opcodes

**Method:** as a moderator, use the client's ban-by-name and tattle/report UI.
**Expected from source:** server logs `Unhandled packet` for `0k` / `T`; nothing
happens in game. `0e` (ban by server id) likewise.

### 11. Vote kick

**Method:** 2-player room, both vote to kick each other's target.
**Expected from source:** with 2 clients, `kickVoters.size() > 1` and
`>= clients - 1` means **both** must vote; a single vote does nothing.

### 12. Ghost mode

**Method:** enable the ghost/spectator option (if reachable) or set
`collisionCheckGhost` in a local copy of `settings558b.ini`.
**Expected from source:** with the flag on, hit detection and remote updates use
`xqXvQHh.player<id>MC` positions instead of the local clip.

### 13. Cosmetics

**Method:** equip a two-colour spinner and a pet with distinct colours; compare
the lobby preview with the in-game sprite.
**Expected from source:** spinner tinted at alpha 75, pet at alpha 100, both using
`colorMC0` / `colorMC1`.

### 14. Quickstart

**Method:** enter quickstart from the title screen.
**Expected from source:** the room name starts with `!` and renders as
`Quick Start <name>`; names come from `sF*` / `sL*` pools in the ini.

## 8.3 Prerequisites for running any of this

1. A Flash player that can load a local SWF (standalone projector or a browser
   with the plugin). Nothing is installed here; installing one is an explicit
   decision, not part of this workspace.
2. The server stack: MySQL + `Import database/ballistick_struct.sql`, a PHP web
   root at `htdocs/stickarena`, and `ballistickemu` built with Maven.
3. A **copy** of `sab558.swf` pointed at the local server. The shipped file
   already targets `127.0.0.1`, but do not edit the original in place — copy it
   outside the tracked tree first (see `AGENTS.md` §2).
4. Two clients for anything involving hit detection, prediction or vote kick.

## 8.4 What would upgrade a claim from [C] to "runtime-verified"

Add a row to this table with the date, the client build, the test id and the
observed result. Keep the source claim next to it so a mismatch is obvious.

| test | date | result | notes |
| --- | --- | --- | --- |
| — | — | — | no runtime tests performed yet |
