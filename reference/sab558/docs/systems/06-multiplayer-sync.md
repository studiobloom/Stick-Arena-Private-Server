# 6. Multiplayer synchronisation

The client is authoritative for its own player and for the damage it receives.
The server is a room-scoped relay. Everything below is text on one null-terminated
socket; there is no binary framing, no prediction rollback and no server tick.

## 6.1 Transport

| property | value | source |
| --- | --- | --- |
| socket | `XMLSocket` to `sServerURL[n]:sConnectPort[n]` | `frame_1/DoAction.as:4755`, `:1620` |
| framing | null-terminated UTF-8 strings | `Main.java:69` |
| user id width | **3** characters (`IDLEN`) | `:8384` |
| max message | game 45, lobby 135 | `sMaxMsgLen`, `sMaxMsgLenLobby` |
| policy file | `<policy-file-request/>` answered by the server | `StickNetworkHandler.java:72-77` |

Numbers are encoded with `pad(n, width)`, which zero-pads and keeps a leading
`-` for negatives (`frame_1/DoAction.as:215-233`), so every field is fixed width
and signed.

## 6.2 Outbound packets

All built in `stick.prototype.*` (`frame_1/DoAction.as:8926-9030`).

| opcode | name | exact payload after the opcode | line |
| --- | --- | --- | --- |
| `1` | position | `x*10` (5), `y*10` (5), `facing` (2), moving (1), walk (1), `xVel*1000` (5), `yVel*1000` (5), rotation (3), invulnerable (1) | `:8959-8977` |
| `2` | weapon-spawn timers | 5 chars per weapon spawn point | `:8948-8958` |
| `4` | attack | `x` (4), `y` (4), rotation (3), weapon (1) | `:8978-8989` |
| `5` | weapon pickup | weapon (1), spawn index (1) | `:8990-8994` |
| `6` | damage taken | damage (2), weapon (1), angle (3) | `:8995-9003` |
| `7` | death | victim id (3), weapon (1), angle (3) | `:9003-9011` |
| `8` | spawn | `x` (4), `y` (4) | `:9011-9015` |
| `9` | chat | message | `:9015-9019` |
| `00` | private message | target id (3), `P`, message | `:9019-9023` |
| `K` | vote kick | target id | `:9023-9027` |
| `T` | tattle | target id (3), reason code | `:9027-9030` |

`x`/`y` in `1` are **world-relative** (`clip._x - xqXvQHh._x`) and scaled by 10,
so the wire precision is 0.1 px. Velocities are scaled by 1000 and clamped to
±9999 (`Math.max(-9999, …)`), which is why they use 5 characters.

`[D]` A full position packet is 28 field characters + 1 opcode + 3 uid = 32
bytes, plus the `M` wrapper the server adds = 33. At the 65 ms cadence that is
≈ 15.4 packets/s per sender; in a 6-player room each client receives
6 × 15.4 × 33 ≈ **3.0 kB/s** (double that if the server also echoes to the
sender, which this server does).

## 6.3 Send cadence

| mechanism | value | source |
| --- | --- | --- |
| periodic position send | `setInterval(sendFunction, minSendTime)` = **65 ms** (~15.4 Hz) | `:7327-7332` |
| compatibility servers | `minSendTimeCompat` = **130 ms** (~7.7 Hz) | `sMinSendTimeCompat` |
| immediate send | facing change sets `sendImmediate`, flushed next frame | `:9356`, `:2957-2961` |
| keepalive | `sendKeepAlive()` every **3000 ms** | `sKeepAliveTime`, `:7027` |
| weapon timers | opcode `2` piggybacks on the position tick | `:8948` |

`[C]` The immediate-send flag exists so that a direction change is not delayed by
up to 65 ms, which would make remote players look like they turn late.

## 6.4 Inbound dispatch

`XMLSocket.prototype.onData` (`frame_1/DoAction.as:8809-8917`) switches on the
first character:

| prefix | meaning | handler |
| --- | --- | --- |
| `M` | relayed message | if body starts with `1` → applied immediately to that player's clip (`newSocket`), else pushed to `socketStack` (`:8815-8830`) |
| `C` | player joined | `addPlayer` / `addPlayerLobby` |
| `D` | player left | `removePlayer` / `removePlayerLobby` |
| `A` | login accepted | `receiveAuthentication` |
| `U` | user list / user info | `updatePlayerLobby` / `updateGameState` |
| `0x` | lobby & control packets | `01`, `04`, `06`, `07`, `08`, `09`, `0a`, `0c`, `0e`/`0f`, `0g`, `0h`, `0j` |

The queued `M` bodies are drained once per frame by `socketCalls()`
(`:4824-4884`), which dispatches on the **second** character (the opcode inside
the relayed packet):

| inner opcode | meaning | client handler |
| --- | --- | --- |
| `4` | someone attacked | `kkXcpL` → plays the swing, then `qxTtuh` hit-tests **my** player |
| `5` | someone switched weapon | `changePlayerWeapon`, `kklhUe` |
| `6` | someone took damage | `remotePlayerDamage` (visuals only) |
| `7` | someone died | `vzvxUc` (kill feed, score, corpse) |
| `8` | someone spawned | `vwaUVs` |
| `9` | chat | `remoteChatMsg` |
| `2` | weapon-spawn timers | `updateWeaponSpawnTimers` |
| `K` | vote kick | `vwPzUs` |
| `U` | full player state | `updateGameState` |

`[C]` Note the asymmetry: opcode `6` (damage) is *sent* by the victim but only
produces visuals on other clients — no client other than the victim tracks HP for
a remote player. Death is the only cross-client health event, and it arrives as
opcode `7`.

## 6.5 Remote player reconstruction

Two mechanisms, chosen per frame (`updateRemotePlayers`, `:3803-3828`):

1. **new packet** → `updatePlayer(...)` (`:4345-4419`), which
   - records `remoteAvgPing` as the mean of the last `sPingAvgPeriod` (10)
     inter-packet deltas,
   - re-runs the **same** movement integrator for
     `approximateFrameDelay = round(ping / 33 + 3)` frames (standard) or
     `round(ping / frameDeltaTime / 4 + 5)` (compatibility) (`:4380-4388`),
   - after each simulated frame does `_x += (absX - _x) / remoteSmoothing`
     with `sRemoteSmoothing = 8`,
   - smooths rotation with `sRemoteRotSmoothing = 4`.
2. **no new packet** → `remotePlayerPrediction()` (`:4453-4491`) continues the
   same simulation locally.

So a remote player is a small deterministic re-simulation of their last known
state, then blended toward it. `[D]` With `ping = 100 ms`, the client simulates
`round(100/33 + 3) = 6` frames (≈ 176 ms) ahead of the packet before blending,
which roughly covers the round-trip delay.

`[U]` The integrator re-simulation uses the *local* player's acceleration
constants for remote players (`ygsfeyb` reads `player.lqkTiW` / `player.maxVel`),
so all players are assumed to have the same physics. Weapons with different
`walkingSpeed` are handled through `qkUfJI`, which is replicated. Any per-client
tuning difference would desync predictions.

## 6.6 The server's relay (and why the echo is safe)

`GamePacketBroadcastHandler.java:30` does:

```java
client.getRoom().BroadcastToRoom(
    StickPacketMaker.getBroadcastPacket(Packet, client.getUID()));
```

`BroadcastToRoom` (`Types/StickRoom.java:89-110`) writes to **every** client in
the room, including the sender, and `getBroadcastPacket` prepends `M` + sender
uid. So each client receives its own attack/position packets back.

`[C]` The echo is not just safe, it is **load-bearing**. `checkConnection()`
(`:3146-3154`) boots the client to the title screen when
`getTimer() - lastMessageRecieved > serverTimeout`, and `sServerTimeout` is
**10000 ms**. `lastMessageRecieved` is only updated in `XMLSocket.onData`
(`:8811`). A solo player therefore has no inbound traffic except the echo of its
own packets.

> **Runtime check (2026-11-04).** A harness build that excluded the sender from
> the room broadcast caused the client to drop to the title screen after ~10 s
> (`disconnect` in the wire log at 22:12:06, exactly 10.3 s after the last
> server→client packet). Relaying to all members — as
> `StickRoom.BroadcastToRoom` does — keeps the session alive indefinitely. This
> also explains why the Java server's broadcast includes the sender.

`[C]` The echo is safe because:

- position packets (`1`) are applied to `xqXvQHh.player<uid>MC` — for the sender
  that is the invisible runtime copy, not the visible rig `gxqKQk`, so the echo
  does not fight the local simulation;
- attack packets (`4`) only trigger hit detection inside
  `if(textMC.localIdText.text != 0)` (`frame_1/DoAction.as:4079`), which is false
  for the local player, so nobody damages themselves with their own echo;
- death packets (`7`) are guarded by `if(a != k)` in `vzvxUc` (`:5060`).

## 6.7 Compatibility mode

`serverType[n] == "COMPATIBILITY"` switches a whole set of values
(`initializeRoundVariables`, `:7275-7290`):

| value | standard | compatibility | source |
| --- | --- | --- | --- |
| acceleration | 3 | **2** | `sPlayerAcc` / `sPlayerAccCompat` |
| max speed | 9 | **6** | `sPlayerMaxVel` / `sPlayerMaxVelCompat` |
| send interval | 65 ms | **130 ms** | `sMinSendTime*` |
| scroll speed | 6 | **1** | `sScrollSpeed*` |
| max ping | 275 | **800** | `sMaxPing*` |
| reload modifier | 1 | **1.5** | `sReloadModifierCompat` |

`[C]` Compatibility mode also changes which map list is used
(`mapListCompat`, 20 entries, 15 classic) — see [04](04-maps.md) §4.5.

## 6.8 Confirmed gaps

| item | evidence | effect |
| --- | --- | --- |
| client sends `0e`, `0k`, `T`; server has no handler | `frame_1/DoAction.as:5800,5808,9029` vs `PacketHandlerLobby.java` / `PacketHandlerGame.java` | server logs `Unhandled packet`; the mod-ban and tattle UI do nothing |
| server sends error `42` and `5`; client handles only `0`–`4` | `recieveError`, `:5677-5785` | full/lab-pass rooms show no specific message |
| `stick_arena.php` has no `report_player` branch | `frame_1/DoAction.as:5293` vs `stick_arena.php` | the report dialog "succeeds" (HTTP 200) but nothing is stored |

## 6.9 Open questions

- `[U]` Whether the retail server echoed packets to the sender. The 558 client
  tolerates it, but it doubles downstream bandwidth in a 6-player room.
- `[A]` `sMaxPing=275` and `sMinFPS=12` feed `checkPerformance()`, which boots
  players to the lobby; the exact thresholds and grace periods were not traced.
- `[U]` `T` (tattle) has a reason code but no server handler; whether the retail
  backend consumed it is unknown.
