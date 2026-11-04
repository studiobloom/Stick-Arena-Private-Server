# runtime/ — local runtime verification harness

Everything here exists so the **original `sab558.swf` can be executed** and its
behaviour observed without modifying the client, the server, or the machine.

Nothing here is shipped game code. It is test scaffolding.

```
runtime/
├── tools/            Ruffle (portable, pinned, checksum-verified)
├── harness/          stub server, window capture, key input, scenario driver
├── http/             test-time config overlay (settings558b.ini with the two
│                     TEMP DEV switches flipped; the repo file is untouched)
├── state/            per-client Ruffle save/config/cache dirs (git-ignored)
└── evidence/         one directory per scenario: screenshots, packets, result
```

## Why Ruffle

No Adobe Flash Player runtime is installed on this machine (checked: no
`flashplayer.exe`, no `pepflashplayer.dll`, no `Macromed\Flash`, no browser
plugin). Ruffle is a Flash Player emulator and the only runtime available.

It is **not** Adobe Flash. Behaviour that depends on AVM1 or rendering edge cases
is marked inconclusive in `docs/systems/09-runtime-evidence.md` rather than
counted as verified.

## Quick start

```bash
cd reference/sab558
bash runtime/tools/fetch_runtime.sh            # ~21 MB, checksum-verified
python runtime/harness/run_scenario.py quickstart
```

The driver starts the stub server (HTTP :80, game socket :1138), launches one or
two Ruffle windows with isolated storage, sends real keyboard input, captures the
windows and writes `runtime/evidence/<scenario>/result.json`.

## The stub server is a test double

`harness/stub_server.py` re-implements the parts of
`ballistickemu/src/ballistickemu/**` the client needs to reach a match. Every
packet format is transcribed from `StickPacketMaker.java` with the source line in
a comment. It deliberately does **not** implement MySQL persistence, lab-pass
logic, moderation, or round arbitration — see
`docs/systems/09-runtime-evidence.md` §9.7 for what still needs the real server.

## Capturing the window

Ruffle renders through a GPU surface, so a normal screen grab comes back white.
`harness/capture_window.ps1` uses `PrintWindow(..., PW_RENDERFULLCONTENT)` to ask
DWM for the composed surface, which works.

## Input

`harness/send_keys.ps1` sends real `keybd_event` down/up pairs, because the
client polls `Key.isDown` per frame — `SendKeys` text alone is not enough, and a
60 ms tap can fall between frames (use ~400 ms for attacks).

## Scenarios

| scenario | what it does |
| --- | --- |
| `login-lobby` | title screen → login form → lobby (uses the unmodified settings) |
| `quickstart` | auto quickstart → room created → in-game |
| `movement` | holds each direction in run and walk mode, measures speed from packets |
| `collision` | runs into walls, counts velocity sign flips |
| `two-clients` | two clients in one room, mutual position packets |
| `round-timer` | ~340 s observation of the round clock and summary |

## Caveats

- Ruffle's `attachSound` lookup resolved four case-mismatched linkage names that
  Adobe Flash would likely reject; that test is inconclusive here.
- The automated scenarios flip `sAutoQuickStart`/`sSkipIntro` through the
  `http/` overlay. Those are the two switches the client itself labels
  `/// TEMP DEV VALUES ///`.
