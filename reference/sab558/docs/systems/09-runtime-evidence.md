# 9. Runtime evidence

This document records what was actually **observed** running the original
`sab558.swf` against a local endpoint, as opposed to what the source says.

Every claim here has an artifact under `runtime/evidence/<scenario>/`
(window captures, wire logs, `result.json`). Nothing in this file is inferred.

## 9.1 What "runtime" means here

| component | what ran |
| --- | --- |
| client | **the original, unmodified `htdocs/stickarena/sab558.swf`** |
| runtime | **Ruffle 0.7.1** (`runtime/tools/ruffle/ruffle.exe`, SHA-256 of the zip in `runtime/tools/CHECKSUMS.txt`) |
| server | `runtime/harness/stub_server.py`, a test double transcribed from the Java handlers (see §9.2) |
| web tier | the same harness, serving the repository's `htdocs/stickarena` read-only |

**Ruffle is a Flash Player emulator, not Adobe Flash.** It is the only Flash
runtime available on this machine (no `flashplayer.exe`, no `pepflashplayer.dll`,
no `Macromed\Flash`, no PHP/MySQL/JDK for the real server). Consequences:

- behaviour that depends on AVM1 edge cases or rendering details can differ from
  Flash Player; such cases are marked **inconclusive** rather than passed;
- anything observed here is *real client code executing*, not a simulation of it.

The window is captured with `PrintWindow(PW_RENDERFULLCONTENT)`
(`runtime/harness/capture_window.ps1`); a plain screen grab of Ruffle's GPU
surface returns white.

## 9.2 Harness fidelity

`stub_server.py` is a test double, not the shipped server. Every packet it emits
is transcribed from `ballistickemu/src/ballistickemu/Tools/StickPacketMaker.java`
and the `Lobby/handlers/*` classes, with the source line noted in the file. It
implements: capacity check, login, room list, create/join, room detail, room
variables, chat, private messages, vote kick, inventory/ticket stubs, and the
in-game relay of opcodes `1/2/4/5/6/7/8`.

It does **not** implement: MySQL persistence, lab-pass/VIP logic, moderator
actions, map storage, or round arbitration. Tests that need those are listed as
"needs the real server" in §9.6.

## 9.3 Environment setup (reproducible)

```bash
cd reference/sab558
bash runtime/tools/fetch_runtime.sh          # downloads + verifies Ruffle
python runtime/harness/run_scenario.py quickstart
```

`run_scenario.py` starts the harness, launches one or two Ruffle windows with
**isolated** save/config/cache directories under `runtime/state/`, sends real
keyboard input (`send_keys.ps1`), captures windows, and writes `result.json`.

Test-time changes are confined to the `runtime/http/` overlay; the repository's
`settings558b.ini` and map files are never modified.

| scenario | overlay change | why |
| --- | --- | --- |
| quickstart / movement / collision / two-clients / combat / round-timer | `sAutoQuickStart=1`, `sSkipIntro=1` | the client's own `/// TEMP DEV VALUES ///` switches; avoids UI automation |
| login-lobby | `sSkipIntro=1` only | login must go through the real form |
| round-timer | additionally `sEnforcePerformance=0` | `PrintWindow` stalls the GPU renderer; the client's FPS watchdog (`sWarnFPSBoot=3`, ≤12 fps) then boots it to title after 15 s. The watchdog is not what the test measures. |
| combat | shared-spawn test maps (`make_test_maps.py`) | two clients must overlap to land a hit; only `&sp=` differs |

Everything else — packet formats, timing constants, gameplay values — is the
shipped 558 configuration.

## 9.4 Results

| # | test | expected (source) | observed | verdict |
| --- | --- | --- | --- | --- |
| 1 | client boots, loads config | `version_check.php` + `settings558b.ini` + `upgradevalues558.ini` + `languagefilter.ini` + `mapEditorTiles.csv` | all five fetched in order within 200 ms of SWF load | **pass** |
| 2 | capacity handshake | `08<key>` with `key = ijsjfnsdjfu` | `08Hx09TdCC62Nwln1P` on every connect | **pass** |
| 3 | quickstart joins a match | create `!<random>` room, load a stock map, spawn | room created, map loaded, spawn packet `8` sent | **pass** |
| 4 | run speed | ~4.9 px/frame (167 px/s) | **4.94 px/frame, 168.9 px/s** | **pass** |
| 5 | walk speed (V held) | ~2.2 px/frame (75 px/s) | **2.24 px/frame, 76.1 px/s** | **pass** |
| 6 | collision response | velocity reflects at `× −0.5` | 37 sign flips in 221 position packets while pressed against walls | **pass** |
| 7 | two clients, one match | B joins A's room; both receive each other | B joined `!64059`; 318 position packets each way | **pass** |
| 7b | victim-side damage | victim applies damage and sends `6` | 12 damage packets, **all from the victim's uid**, each 5 (fist) | **pass** |
| 7c | death + respawn | 60 HP / 5 dmg = 12 hits; respawn 150 frames | 12 hits = exactly 60; one `7` packet; respawn **4.38 s** later (predicted 4.41) | **pass** |
| 8 | echo keeps the session alive | server→client traffic resets `lastMessageRecieved` | without the echo the client dropped at 10.3 s; with it, stable | **pass** |
| 9 | attack input | Space produces opcode `4` | `4` observed after a 400 ms hold (a 60 ms tap was missed) | **pass** |
| 9b | login → lobby | `09<user>;<pass>` → `A` → `0c`, `01`, `03_` | observed exactly that (`09 1234;1234`) | **pass** (protocol only) |
| 10 | round clock + end | 300 s round, 11 s summary, 20 s ad | clock is server-authoritative; end-to-end 300 s not completed | **partial** (§9.5) |
| 11 | missing sound linkages | 3 names have no symbol at all | Ruffle logs `Sound 'dragVolume.wav' not found`, `'flamethrowerimp00.wav' not found`, `'railgunimp00.wav' not found` | **pass (3 of 7)** |
| 12 | case-mismatched sound names | 4 names differ only in case | Ruffle resolved them silently → **inconclusive**: Ruffle's linkage lookup is not proven case-sensitive like Flash's | **inconclusive** |

### 9.4.1 Movement detail

`runtime/evidence/movement/result.json`, best free run over four directions:

```
run : 172 samples, max 4.968 px/frame, p95 4.943 px/frame -> 168.9 px/s
walk: 171 samples, max 3.495 px/frame, p95 2.239 px/frame ->  76.1 px/s
```

The walk `max` is an outlier (the frame where V was released); the p95 is the
plateau and matches the derived steady state.

### 9.4.2 Two-client detail

`runtime/evidence/two-clients/result.json` and `packets.log`:

```
A: 02F100!64059        create room, map F (Brawlers Burrow)
A: 05mp=F056HGI2JE381B49D7AC
B: 04!64059 -> 04F11331
B: 06!64059;mp -> 06mp=F056HGI2JE381B49D7AC
B: 03!64059            join, members=2
S->C 002 M0031...  x318   (A receives B's positions)
S->C 003 M0021...  x318   (B receives A's positions)
```

Both windows show the same room name in the entry banner
(`shot_B_joined.png`: "YOU HAVE ENTERED 'QUICK START 64059' - BRAWLERS BURROW").

### 9.4.3 Combat detail

`runtime/evidence/combat/result.json`, `packets.log`, `shot_after_attack.png`,
`shot_victim.png`:

```
A: 002 801500200        spawn (both at the same tile)
B: 003 801500200
A: 002 4015002001800    attack x=150 y=200 rot=180 weapon=0 (fist)
B: 003 6050359  x12     damage 5, weapon 0, angle 359   <- sent by the VICTIM
B: 003 70020359         death: killer 002, weapon 0, angle 359
B: 003 801500200        respawn 4.38 s after the death packet
```

Three source claims are confirmed at once:

1. **damage is victim-side** — the attacker sent 16 `4` packets and zero `6`
   packets; every `6` came from the victim (`docs/systems/03` §3.4);
2. **damage value 5 for the fist** matches `weapons[0].damage`
   (`initializeWeapons`, `:1825`) and 12 × 5 = 60 = `playerMaxHP`;
3. **respawn is 150 frames** — measured 4.38 s at ~34 fps vs 4.41 s predicted
   (`docs/systems/05` §5.4).

The victim's screen also rendered the kill message from the ini's
`sKillTextPre/Post` table ("GAVE YOU THE 'OL ONE-TWO"), which confirms the
per-weapon kill-text path (`:3495-3508`, `:5073`).

### 9.4.4 Login → lobby detail

`runtime/evidence/login-lobby/`:

```
002 08Hx09TdCC62Nwln1P          capacity check
002 091234;1234                 login: "09" + user + ";" + pass
S->C A002################1234...  login accepted (uid 002, name padded to 20)
002 0c                          inventory request
002 01                          room list
002 03_                         enter lobby
```

The client's login form (`shot_filled.png`) is opened from the title menu and
submits over the socket, not HTTP — confirming `docs/protocol.md` §2 and
`docs/systems/07` §7.2. The test double accepts any credentials, so this
verifies the **client's** login path, not the server's authentication policy
(which needs MySQL).

## 9.5 Round timing

The client's round clock is **server-authoritative**. `recieveRoomDetail`
(`:5205`) sets `tqJqPc = <server value> - summary - ad` every time the client
asks for room detail, and it asks whenever its local countdown has drifted more
than 15 s (`updateRoundTimer`, `:3110-3114`).

> **First run (2026-11-04 00:39, invalid).** The harness answered `04` with a
> constant `roundTime = 300`, so every re-sync reset the client's countdown and
> the round never ended — still running at 330 s. That is the harness's fault,
> not the client's, and it is the clearest demonstration that the clock is not
> client-owned.

The harness now mirrors `StickRoom`'s timer (300 s counting down, reset at −30,
`StickRoom.java:259-265`).

**Second run (2026-11-04 00:47, also inconclusive).** With the corrected harness
the client stayed in-round, but the run was cut short by the client's own
inactivity watchdog: `checkNoInput()` boots to title after
`sNoInputBootGameDelay` = 120 s without input, and the periodic keep-alive key
taps did not reset `noInputTime` reliably. The client dropped at 118 s.

What is established:

- the round clock is **not** client-owned — a constant server value keeps the
  round alive indefinitely, and the client re-syncs from `04` every ~16 s;
- `endRound()` is driven by `tqJqPc <= 0` (`:3126-3130`), where `tqJqPc` is the
  server value minus `summary + ad` (`:5205`).

What is **not** established: the observed wall-clock duration of a full
300 s round plus the 11 s summary and 20 s ad. Doing that needs either a
foreground, non-idle client for 5.5 minutes or a build that disables
`checkNoInput` — neither was done, so no duration is claimed.

## 9.6 Discrepancies found by running the client

| # | finding | evidence | action taken |
| --- | --- | --- | --- |
| D1 | The walk key is **V** (`sKWalk0=118`), not W. `keyIsDownMulti("W")` reads the `kW[]` walk array; the letter is a slot name. | V produced `walk=1`, W did not | corrected `docs/systems/02-movement-collision.md` |
| D2 | `ijsjfnsdjfu = "Hx09TdCC62Nwln1P"` is the **`08` capacity key**, not an RC4 key. `class.rc4crypt.php` is required but never used. | `08Hx09TdCC62Nwln1P` on every connect; no `new rc4crypt` anywhere | retracted the RC4 assumption in `docs/client-sab558.md` and `docs/architecture.md` |
| D3 | The server→sender echo is **required**, not optional: the client drops to the title after `sServerTimeout` = 10 s without inbound data. | 10.3 s disconnect in a non-echoing harness build | documented in `docs/systems/06-multiplayer-sync.md` |
| D4 | A 60 ms Space tap is not seen as an attack; ~400 ms is. | probe runs | noted here; the client polls `Key.isDown` per frame |
| D6 | The harness's first `04` reply used a constant `roundTime`, and the round never ended — the client re-syncs its clock from the server. | §9.5 first run | stub now counts down like `StickRoom`; documented that the clock is server-authoritative |
| D7 | Ruffle switches to fullscreen by itself at some point (captures become 2560x1440), so `capture_window.ps1` now downscales to 1024 px. | round-timer shots 290-330 in the first run | capture helper gained `-MaxWidth` |
| D5 | In quickstart the client never sends `09`: the server has to invent the name (`NewClientHandler.setUpAsQuickplay`). The client displays its own local name, so the player list and the HUD can disagree. | no `09` in any quickstart session; `U` packet carried the stub's placeholder | noted; needs the real server to confirm name generation |

## 9.7 What still needs the real Java server

These cannot be tested with the stub because the behaviour lives in the server or
in MySQL:

- login against the `users` table, bans, IP bans, ticket timers;
- lab-pass/VIP room visibility and joining;
- vote-kick enforcement and room blacklisting;
- round arbitration (`updateStats(getWinner())` at `RoundTime == -1`);
- map save/load through `api.php` and the `maps` table;
- `stick_arena.php` stats.

Running those requires MySQL + PHP + a JDK 11+ build of `ballistickemu`. None is
installed; installing them is a system-level change and was not done.

## 9.8 Evidence index

| path | contents |
| --- | --- |
| `runtime/evidence/quickstart/` | first successful boot, room creation, in-game screenshot |
| `runtime/evidence/movement/` | speed measurement + `result.json` |
| `runtime/evidence/collision/` | wall-contact sign flips |
| `runtime/evidence/two-clients/` | two clients, join, mutual position packets, screenshots |
| `runtime/evidence/combat/` | 12 damage packets, death, 4.38 s respawn, victim + attacker screenshots |
| `runtime/evidence/login-lobby/` | login form, `09` → `A` → lobby packet sequence |
| `runtime/evidence/round-timer/` | clock observation (see §9.5) |
| `runtime/evidence/keyprobe*/` | key-mapping probes (D1, D4) |
| `runtime/evidence/*/packets.log` | raw wire log for every scenario |
