# 558 socket protocol

Two independent sources are used here:

- **Client side:** the decompiled ActionScript in
  `extracted/scripts/as/frame_1/DoAction.as` (line numbers below refer to that
  file).
- **Server side:** `ballistickemu/src/ballistickemu/**` (line numbers as in the
  repository).

Where the two disagree it is stated explicitly; nothing is smoothed over.

## 1. Transport

| property | value | evidence |
| --- | --- | --- |
| socket type | Flash `XMLSocket` (raw TCP, no HTTP) | `DoAction.as:4755` |
| host/port | `sServerURL<n>` / `sConnectPort<n>` from `settings558b.ini`; shipped value `127.0.0.1:1138` | `settings558b.ini` `SERVER LIST`; `Main.java:33` |
| framing | null-terminated UTF-8 strings, terminator `\0` on both directions | `Main.java:69` |
| pre-flight | Flash sends `<policy-file-request/>`; server replies with the policy XML | `StickNetworkHandler.java:72-77` |
| max message | lobby 135 chars, game 45 chars (client constants) | `settings558b.ini` `sMaxMsgLen*` |
| idle timeout | 50 idle events × 10 s | `Main.java:66`, `StickNetworkHandler.java:102` |
| user id length | `var IDLEN = 3;` — ids are 3 characters wide | `DoAction.as:8384` |

All packets are ASCII text. There is no checksum, length field or encryption on
this socket.

## 2. Client → server

Opcode is the leading character(s); fields are concatenated with no separators
unless a `;` is shown.

| opcode | purpose | wire form (from client) | client line | server handler |
| --- | --- | --- | --- | --- |
| `00` | generic send to a user | `00<uid:3>P<msg>` | 9021 | `GenericSendDataHandler` |
| `01` | request room list | `01` | 1652 | `RoomRequestHandler` |
| `02` | create room | `02<mapId><cycleMode><isPrivate><roomName>` (7+ fields variant adds `<isBallistick>` and a VIP list) | 1641, 1648 | `CreateRoomHandler` |
| `03` | join room (or return to lobby as `03_`) | `03<roomName>` | 1634 | `NewClientHandler` |
| `04` | room detail | `04<roomName>` | 1657 | `RoomDetailRequestHandler` |
| `05` | set map cycle list | `05<setStr>` | 1661 | `SetMapCycleListHandler` (game) |
| `06` | request map cycle list | `06<getStr>` | 1666 | `MapCycleRequestHandler` |
| `07` | request a player's IP | `07<uid:3>` | 5788 | `ModRequestIPHandler` → replies `07<ip>` |
| `08` | capacity / server-key check | `08<key>` | 1624 | `CheckCapacityHandler` |
| `09` | login | `09<username>;<password>` | 8946 | `LoginHandler` |
| `0a` | claim cred ticket | `0a` | 8928 | `GiveTicketHandler` |
| `0b` | buy item | `0b<itemCode:3><r0:3><g0:3><b0:3><r1:3><g1:3><b1:3>` | 8940 | `BuyItemRequestHandler` |
| `0c` | inventory request | `0c` | 8932 | `InventoryRequestHandler` |
| `0d` | set active item | `0d<itemId>` | 8936 | `SetActiveItemRequestHandler` |
| `0e` | moderator ban by server id | `0e<serverId>;<period>;<msg>` | 5800 | **no handler** |
| `0f` | moderator ban | `0f<userName>;<period>;<msg>` | 5796 | `ModBanHandler` |
| `0g` | moderator warn | `0g<uid:3><msg>` | 5792 | `ModWarnHandler` |
| `0h` | find player | `0h<userName>` | 5804 | `FindRequestHandler` |
| `0i` | map rating | `0i<rating>` | 5836 | `MapRatingHandler` (game) |
| `0k` | moderator ban by name | `0k<userName><reasonCode>` | 5808 | **no handler** (server uses `0l`) |
| `0l` | — | not sent by this client | — | `ModBanNameHandler` |
| `0m` | — | not sent by this client | — | `ModKillRoomHandler` |
| `0j` | — | not sent by this client | — | `ModGlobalHandler` |
| `1` | position/state update | `1<pad5><pad5><state><pad1><pad1><pad5><pad5><pad3><pad1>` | 8976 | relayed (game) |
| `2` | movement update | `2<...>` | 8957 | relayed (game) |
| `4` | game action | `4<pad4><pad4><pad3><str>` | 8988 | relayed (game) |
| `5` | game action | `5<str><pad1>` | 8993 | relayed (game) |
| `6` | game action | `6<pad2><angle><pad3>` | 9001 | relayed (game) |
| `7` | kill / damage | `7<pad IDLEN><angle><pad3>` | 9009 | `KillHandler` |
| `8` | game action | `8<pad4><pad4>` | 9013 | relayed (game) |
| `9` | chat | `9<message>` | 9017 | `GeneralChatHandler` |
| `K` | vote kick | `K<uid>` | 9025 | `VoteKickHandler` |
| `T` | tattle / report | `T<uid:3><tattleCode>` | 9029 | **no handler** |

The `1/2/4/5/6/8` game packets are **not interpreted** by the server:
`GamePacketBroadcastHandler.java:30` re-broadcasts them to the room unchanged.
Gameplay state is therefore client-authoritative in this server.

`07` is worth calling out: the decompiled function is named `sendReportUser`
(`DoAction.as:5787`) but the client's reply handler `recieveReportUser`
(`DoAction.as:5273`) expects `IP Address:<ip>`, and the server answers with the
remote IP (`ModRequestIPHandler.java:28-33`). The name is misleading; the
behaviour is consistent.

## 3. Server → client

The client dispatches on the first character, then on the first two characters
when it is `0` (`XMLSocket.prototype.onData`, `DoAction.as:8809-8917`).

| prefix | meaning | payload format | client handler | server builder |
| --- | --- | --- | --- | --- |
| `A` | login accepted | `<uid:3><name padded to 20 with '#'><r:3><g:3><b:3>` then `;`-separated `kills;deaths;wins;losses;roundsStarted;pass;daysToPassExpiry;ticketWaiting;cash;userLevel` | `receiveAuthentication` (5593) | `StickPacketMaker.getLoginSuccess` (155) |
| `C` | player joined | `<uid:3>` | `addPlayer` / `addPlayerLobby` | `getNewPlayerUID` (45) |
| `D` | player left | `<uid:3>` | `removePlayer` / `removePlayerLobby` | `Disconnected` (86) |
| `M` | relayed message | `<uid:3><body>` | pushed to `socketStack` (or routed to a player clip for `M…1…`) | `getBroadcastPacket`, `GeneralChat`, `GenericSendPacket` |
| `U` | user list / user info | `<uid:3><name:20><r:3><g:3><b:3>` + `;`-separated stats | `updatePlayerLobby` | `getUserList`, `getUpdateUserList`, `getUserDataGame` |
| `01` | room list | room records | `recieveRoomList` | `getRoomList` (53) |
| `04` | room detail | `<mapId><cycleMode><players><roundTime+31>` | `recieveRoomDetail` | `getSendRoundDetail` (94) |
| `06` | room variables (map cycle) | `<...>` | `recieveRoomVariable` | `getMapCycleRequestResponse` (106) |
| `07` | IP answer | `<ip>` | `recieveReportUser` | `ModRequestIPHandler` |
| `08` | server not full | — | `recieveServerNotFull` | `CheckCapacityHandler` |
| `09` | error | `<code>` | `recieveError` (5677) | `getErrorPacket` (147) |
| `0a` | cred ticket | `<amount>` | `showTicket` | `getCredsTicket` (445) |
| `0c` | owned items | item list | `recieveOwnedItemList` | `getInventoryPacket` (404) |
| `0e`,`0f` | ban notice | `<time>;<message>` | `recieveModeratorBan` | `getBanMsg` (453/463) |
| `0g` | moderator warn | `<message>` | `recieveModeratorWarn` | `getModWarn` (421) |
| `0h` | find-player answer | `<message>` | `recieveFindPlayerResponse` | `getCallbackPacket` (428) |
| `0j` | global message | `<message>` | `recieveGlobalMessage` | `getAnnouncePacket` (413) |

## 4. Error codes

Server (`grep getErrorPacket`): `0` (server full), `1` (IP banned), `2`, `4`
(blacklisted from room), `42` (room full / lab pass required), `5`.

Client (`recieveError`, `DoAction.as:5677-5785`): handles **`0`**, **`1`**,
**`2`**, **`3`**, **`4`** only.

Consequences, confirmed by reading both sides:

- `42` (the most common rejection in practice: full room, or joining a lab-pass
  room without a pass) has no client branch, so the client shows no specific
  message for it.
- `5` likewise has no client branch.

## 5. Version gate

The HTTP gate is separate from the socket:

```
POST ver=558 → version_check.php
    if ($version == 598 || $version == 588 || $version == 558) "result=success"
```

`htdocs/stickarena/version_check.php:12`. The shipped file accepts all three
builds; restricting the server to 558 only requires editing that line (see
`docs/architecture.md` §8 for the client/server gaps that matter more).
