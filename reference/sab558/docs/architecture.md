# Architecture: how 558 is put together

Scope: the Ballistick 558 client plus the server/web/database code that ships in
this repository. Every claim below cites the file it came from. Claims that are
inferred are marked **Assumption**.

## 1. Components

```
            HTTP (80)                                  TCP (1138)
┌──────────────┐   settings558b.ini, upgradevalues558.ini   ┌────────────────────┐
│ 558 client   │   version_check.php, stick_arena.php,      │ BallistickEMU      │
│ sab558.swf   │──►api.php, maps/558/*.dat, *.swf, *.dat ──►│ Java 8 / Apache    │
│ (AVM1, 34fps)│                                            │ MINA, NIO          │
└──────────────┘◄──────────────── XMLSocket ───────────────►│ null-delimited text│
        │                                                   └─────────┬──────────┘
        │                                                             │ JDBC
        │            ┌──────────────────────────┐                     │
        └───────────►│ MySQL  ballistickemu     │◄────────────────────┘
                     │ users, inventory, maps,  │◄── stick_arena.php / api.php
                     │ shop, bans, ipbans, ...  │
                     └──────────────────────────┘
```

| component | entry point | evidence |
| --- | --- | --- |
| Flash client | `htdocs/stickarena/sab558.swf` | `manifests/swf_header.json` |
| Game server | `ballistickemu/src/ballistickemu/Main.java` | `Main.java:33` (port 1138), `Main.java:69` (codec) |
| Web tier | `htdocs/stickarena/*.php` | endpoint literals in the SWF, see `docs/client-sab558.md` §5 |
| Database | `Import database/ballistick_struct.sql` | `CREATE TABLE` statements |
| Static content | `htdocs/stickarena/maps/558/`, `ballistick/ingame/*.swf`, `com/languagefilter.ini` | client string literals |

## 2. Runtime topology (confirmed)

- **One TCP port, two protocols.** The client opens an `XMLSocket`
  (`frame_1/DoAction.as:4755`) to `sServerURL<n>`:`sConnectPort<n>` from
  `settings558b.ini` (shipped value: `127.0.0.1:1138`). Before the game socket,
  Flash sends `<policy-file-request/>` on the same port; the server answers with
  the socket policy (`StickNetworkHandler.java:72-77`). The client comment in the
  server code says the client opens two connections, one for the policy file and
  one for the game.
- **Framing.** MINA's `TextLineCodecFactory(UTF-8, "\0", "\0")` means every
  message is a null-terminated UTF-8 string (`Main.java:69`). There is no binary
  framing, no length prefix and no encryption on the socket.
- **Idle handling.** Sessions idle for more than 50 idle events (10 s each,
  `Main.java:66` + `StickNetworkHandler.java:102`) are closed.
- **State ownership.** The server owns lobby/room membership, map cycle, bans,
  shop/inventory and stats. It does **not** simulate the match:
  `GamePacketBroadcastHandler` relays any packet starting with `1,2,4,5,6,8` to
  the room verbatim (`GamePacketBroadcastHandler.java:30`), so positions,
  attacks and deaths are computed by each client.

## 3. Session lifecycle

| step | client action | server code | evidence |
| --- | --- | --- | --- |
| 1 | POST `ver=558` to `version_check.php` | PHP accepts `558`, `588`, `598` | `htdocs/stickarena/version_check.php:12` |
| 2 | GET `settings558b.ini`, `upgradevalues558.ini` | static files | `frame_1/DoAction.as:3326,3532` |
| 3 | socket connect, send `09<name>;<password>` | `LoginHandler`: splits on `;` (`LoginHandler.java:62`), MD5 (`PasswordHasher`), `SELECT * FROM users WHERE USERname=? AND USERpass=?` | `LoginHandler.java:78-90` |
| 4 | receive `A<UID><name#padded><rgb1><rgb2><kills>;<deaths>;<wins>;<losses>;<rounds>;<pass>;<expiryDays>;<ticket>;<cash>;<level>` | `StickPacketMaker.getLoginSuccess` | `StickPacketMaker.java:155-186` |
| 5 | send `08<key>` (capacity), `01` (room list) | `CheckCapacityHandler`, `RoomRequestHandler` | `PacketHandlerLobby.java:59-84` |
| 6 | send `03<roomName>` to join, or `02...` to create | `NewClientHandler`, `CreateRoomHandler` | `PacketHandlerLobby.java:83,96` |
| 7 | game packets `1,2,4,5,6,8` | relayed to room | `PacketHandlerGame.java:116-120` |
| 8 | `03_` returns to the lobby and triggers a profile refresh | `NewClientHandler.java:35-71` | confirmed by the `03_` branch |

`09` is the login packet: `LoginHandler.java:62` strips the first two characters
and splits the rest on `;`, so the wire form is `09<username>;<password>`.
Usernames longer than 20 characters are rejected and the session is closed
(`LoginHandler.java:63-66`).

### The client does not log in over HTTP (confirmed)

The only `LoadVars` POSTs the 558 client makes to `stick_arena.php` are:

| action | frame | fields | handled by `stick_arena.php`? |
| --- | --- | --- | --- |
| `create` | `frame_2/DoAction.as:279` | `username`, `userpass` | yes (`stick_arena.php:80`) |
| `report_player` | `frame_1/DoAction.as:5293` | `reporter_username`, `reported_username`, `reported_ip`, `msg` | **no branch exists** |

`stick_arena.php` also implements `authenticate`, `player_stats`, `start_round`
and `round_stats`, but nothing in this repository calls them: the SWF
authenticates over the socket, and `htdocs/stickarena/index.php` only embeds the
SWF. They are reachable only by manual HTTP calls. `api.php` is called by the
client with `method=xgen.stickarena.maps.*` and `method=xgen.users.*` literals
(`manifests/as2_strings.json`).

## 4. Responsibility map

### Gameplay

| responsibility | file |
| --- | --- |
| Movement/attack/chat relay | `ballistickemu/src/ballistickemu/Game/handlers/GamePacketBroadcastHandler.java` |
| Kill accounting (`7<target>`) | `Game/handlers/KillHandler.java` |
| Round start/end, map cycle, round time, VIP list, blacklist | `Types/StickRoom.java` |
| Kill/death/win/loss/round persistence | `htdocs/stickarena/stick_arena.php` (`action=round_stats`) |
| Client-side simulation, collision, weapons, spinners, pets | `sab558.swf` (`frame_9` `mainFrame` timeline; `extracted/scripts/as/frame_9/`) |

### Networking

| responsibility | file |
| --- | --- |
| Socket accept, policy file, lobby↔game dispatch | `Tools/StickNetworkHandler.java` |
| Lobby opcode dispatch (`0x`, `9`) | `Lobby/PacketHandlerLobby.java` |
| Game opcode dispatch (`0x`, `1/2/4/5/6/8`, `7`, `9`, `K`) | `Game/PacketHandlerGame.java` |
| Outbound packet construction | `Tools/StickPacketMaker.java` |
| Per-client session state | `Types/StickClient.java` |
| UID allocation | `Tools/UIDTool.java` |
| Chat text, length limits, filter | `Lobby/handlers/GeneralChatHandler.java`, `com/languagefilter.ini` |

### Maps

| responsibility | file |
| --- | --- |
| Map data files | `htdocs/stickarena/maps/558/**/*.dat` (72 files: 20 root, 11 `ballistick/`, 41 `feature/`) |
| Map cycle list | `settings558b.ini` → `sMap0..N`, `sMapCompat0..19`, `nNumClassicMapsCompat=15` |
| Map cycle request/set | `Lobby/handlers/MapCycleRequestHandler.java`, `Game/handlers/SetMapCycleListHandler.java` |
| Map rating | `Game/handlers/MapRatingHandler.java` |
| User map storage (server API) | `htdocs/stickarena/api.php` → `xgen.stickarena.maps.list/get/save`, table `maps` |
| Map editor + tile set | `sab558.swf` `mapEditorFrame` (frame 6), `mapEditorTiles.csv` |
| ~~Map data encryption~~ **retracted** | `class.rc4crypt.php` is required by `stick_arena.php` but never used; maps travel in clear text |

### UI

| responsibility | file |
| --- | --- |
| Screen state machine | main timeline frames 1–22, `docs/client-sab558.md` §3 |
| Dialogs | 45 exported `window*MC` sprites, e.g. `window304JoinGameMessageMC` (5179) |
| Widgets | Flash MX component set under `extracted/scripts/as/__Packages/mx/` |
| Shop / lab-pass modules | `htdocs/stickarena/ballistick/ingame/*.swf` (10 files) |
| Web front end | `htdocs/stickarena/index.php`, `styles/default.css`, `images/` |

### Social

| responsibility | file |
| --- | --- |
| Public chat (`9<msg>` → `M<uid>9<msg>`) | `Lobby/handlers/GeneralChatHandler.java`, `StickPacketMaker.GeneralChat` |
| Private messages | client-side; carried in `M` packets, see `manifests/characters.json` (`window304JoinPrivateMessageMC` = 5179, `privateMessage.wav` = 7879) |
| Find player (`0h<name>`) | `Lobby/handlers/FindRequestHandler.java` |
| Moderator warn (`0g`), ban (`0f`), ban by name (`0l`), global message (`0j`), request IP (`07`), kill room (`0m`) | `Lobby/handlers/Mod*.java` |
| Vote kick (`K<uid>`) | `Game/handlers/VoteKickHandler.java` |
| Highscores | `htdocs/stickarena/stickarena/highscore.php`, `highscoreNew.php` |
| Player report (client `action=report_player`) | **no handler**; see §3 |
| Ranks / trophies | `htdocs/stickarena/images/Rank*.gif`, exported `rank<N>MCLobby*` sprites |

## 5. Server internals

- **Transport:** Apache MINA `NioSocketAcceptor` with a fixed executor filter and
  a 2048-byte read buffer (`Main.java:64-70`).
- **Registries:** `StickClientRegistry` (lobby clients) and `StickRoomRegistry`
  (rooms), both created by `LobbyServer` (`Lobby/LobbyServer.java:36-41`).
- **Rooms:** `StickRoom` holds name, map id, cycle mode, privacy, round time,
  storage key, map cycle list, VIP map, creator, blacklist (`Types/StickRoom.java:45-62`).
- **Shop:** `StickShop.PopulateShop()` reads the `shop` table at startup
  (`Main.java:107`); items are described by `Types/StickItem.java` and
  `Tools/ItemType.java`.
- **Quickplay:** `Tools/QuickplayTool.PopulateNameList()` reads `quickplay_names`
  (`Main.java:112`); the client's quickstart name lists also live in
  `settings558b.ini`.
- **Console:** optional stdin command loop (`ConsoleCommandHandler`) enabled by
  `enable_prompt=true` in `config.properties`.
- **Config:** `ballistickemu/config.properties` (server IP/port, DB credentials,
  `logchat`, `enable_prompt`) and `log4j2.xml`.

## 6. Database (MySQL)

Schema: `Import database/ballistick_struct.sql`.

| table | purpose | key columns |
| --- | --- | --- |
| `users` | accounts + persistent stats | `UID`, `USERname`, `USERpass` (MD5), `user_level`, `passexpiry`, `cash`, `labpass`, `rounds/kills/deaths/wins/losses`, `ticket`, `lastticket`, `red/green/blue`, `ban`, `ip`, `email_address`, `verified`, `creationdate`, `lastlogindate` |
| `inventory` | owned spinners/pets + colours | `userid`, `itemid`, `itemtype`, `red1/green1/blue1`, `red2/green2/blue2`, `selected` |
| `shop` | purchasable item ids + prices | `itemID`, `cost` |
| `maps` | user-created maps | `userid`, `slot_id`, `name`, `mapdata` |
| `bans` | account bans with expiry | `userid`, `playername`, `mod_responsible`, `issuedate`, `enddate`, `reason` |
| `ipbans` | IP bans with expiry | `ip`, `playername`, `mod_responsible`, `issuedate`, `enddate` |
| `quickplay_names` | quickstart name pool | `type`, `value` |
| `pending_verifications` | email verification / recovery keys | `userid`, `validationkey`, `expirydate`, `verificationtype` |

`Import database/example_users.sql` and `map_users.sql` are seed data, not schema.

## 7. Map file format (confirmed)

`maps/558/*.dat` is a plain-text, CR-separated record file. Verified against
`maps/558/__xgenhq.dat` (6,184 bytes):

```
inf=35 24 XGen HQ       &tiles=
0C0003 0W1003 ... (35*24 = 840 space-separated cell tokens)
&sp= 550 100 1250 150 ...      player spawn points (x y pairs)
&ws= 200 100 2 10 ...          weapon spawns (x y type amount groups)
&rt= 300                       (integer field, purpose not documented)
&ts=0                          tile set index
```

- Header `inf=<cols> <rows> <name>`.
- The grid is `cols*rows` tokens; 840 tokens for 35×24 was verified by counting.
- Records are terminated with `\r` (classic Mac line ending), not `\n`.
- The client parses these keys in `frame_1` / `frame_6` (`&tiles=\r`, `tiles=`,
  `&sp=`, `&ws=` appear as literals in `manifests/as2_strings.json`).
- **Assumption:** `&rt=` is the recommended round time in seconds; the literal
  `300` matches the server default round time, but no code path was traced.

## 8. Confirmed gaps between the 558 client and this server

These are observations, not fixes. Each is verifiable by reading the two sides.

| client sends | client evidence | server dispatch | result |
| --- | --- | --- | --- |
| `0e<serverId>;<period>;<msg>` | `frame_1/DoAction.as:5800` | `PacketHandlerLobby` has no `0e` branch | logged as `Unhandled packet` |
| `0k<name><reasonCode>` | `frame_1/DoAction.as:5808` | server implements `0l` (`ModBanNameHandler`) | logged as `Unhandled packet` |
| `T<uid><tattleCode>` | `frame_1/DoAction.as:9029` | no `T` branch in either handler | logged as `Unhandled packet` |

The client *does* handle the server's `0e`/`0f` ban packets
(`frame_1/DoAction.as:8901`), so the inbound side is consistent; only the
outbound moderation opcodes differ.

## 9. Not determinable from 558 material

- Retail server behaviour (`ballistick6.xgenstudios.com`) — only its name and
  port appear in `settings558b.ini`.
- Whether the retail client had the same unhandled-opcode gaps.
- The exact semantics of `&rt=` and of the obfuscated frame label `tasvfsdfveg1`.
