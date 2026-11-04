# 7. Lobby, UI and social features

Everything outside a match lives on main-timeline frames 2–7 and 11–22, driven by
the same `frame_1` code base. The lobby is one screen with four tabs (lobby,
profile, shop, editor) and a chat panel.

## 7.1 Screen map

| frame | label | role |
| --- | --- | --- |
| 2 | `titleFrame` | title / login / quickstart |
| 3 | `lobbyFrame` | room list, user list, chat, create/join |
| 4 | `profileFrame` | spinners, pets, colours, stats |
| 5 | `shopFrame` | shop items, lab pass, cred ticket |
| 6 | `mapEditorFrame` | map editor |
| 7 | `preMain` | transition into a round |
| 11 | `optionsFrame` | quality, blood, particles, language filter, keys |
| 12 | `reportFrame` | report / IP lookup |
| 13 | `roundSummaryFrame` | per-round results |
| 14 | `creditsFrame` | credits |

Frame labels are confirmed in `manifests/swf_header.json` →
`main_timeline_frame_labels`; the tab handlers are
`pressTabLobby/pressTabProfile/pressTabShop/pressTabEditor`
(`frame_3/DoAction.as:941-984`).

## 7.2 Room list

Flow (all client-side, `frame_1/DoAction.as`):

| step | client sends | server replies | client handler |
| --- | --- | --- | --- |
| list | `01` (`sendRoomListRequest`, `:1650`) | `01` + `_0;` + `name` + `passFlag` + `;` per room | `recieveRoomList` (`:5127-5191`) |
| detail | `04<roomName>` (`sendRoomDetailRequest`, `:1654`) | `04` + mapId + cycleMode + players + `roundTime+31` | `recieveRoomDetail` (`:5191-5213`) |
| variables | `06<roomName>;mp` / `;rc` (`sendGetRoomVariable`, `:1663`) | `06mp=<cycle>` / `06rc=<creator>` | `recieveRoomVariable` (`:5213-5273`) |
| join | `03<roomName>` (`sendJoinRoom`, `:1631`) | `C<uid>` per player | `addPlayer` (`:3845`) |
| create | `02<map><cycle><private><name>` or `02<map><cycle><private><ballistick><name>;<vip;vip>` | — | `sendCreateRoom` / `sendCreateRoomBallistick` (`:1636-1650`) |

`[C]` The room string is `displayName + passFlag`, and `getRoomDisplayName()`
strips the trailing flag (`:4567-4573`). A leading `!` marks a quickstart room
and is rendered as `Quick Start <name>`.

`[C]` Naming mismatch worth knowing: the server's flag byte means **needsPass**
(`StickRoomRegistry.GetRoomPacketInfo`, `:81-106`), while the client reads the
same byte with `roomIsBallistick()` and uses it to choose
`roomBallistickLobbyMC` (6651) vs `roomNormalLobbyMC` (6652)
(`frame_1/DoAction.as:4749-4752`). In 558 the two coincide because Ballistick
content is lab-pass gated.

`[C]` The server hides private rooms, full rooms and lab-pass rooms the client
may not join (`GetRoomPacketInfo`), so "the room list is empty" can mean "all
rooms are private", not "no rooms".

## 7.3 Room creation

`pressCreateGameOK` (`frame_3/DoAction.as:745-808`) validates in this order:

1. name length > 2 (`lobbyText[15]`);
2. legal characters (`qkCqjQ`) and room-character set (`isLegalRoomString`);
3. language filter (`containsNoFilteredLanguage`);
4. at least one map-set checkbox (classic / Ballistick / custom / feature);
5. non-empty map list;
6. then builds the cycle with `getMapCycleList(...)` and sends
   `sendCreateRoomBallistick(map, cycle, private, name, isBallistick, vipList)`.

The VIP list is limited to `nMaxVIPListLength = 6` entries
(`sMaxVIPListLength`), managed by `pressAddVIP` / `pressRemoveVIP`
(`frame_3/DoAction.as:395-449`).

## 7.4 Chat

| property | value | source |
| --- | --- | --- |
| send | `9<message>` | `sendChatMsg`, `:9015-9019` |
| receive | `M<uid>9<message>` → `remoteChatMsg` | `:4935-4952` |
| max length | 45 in game, 135 in lobby | `sMaxMsgLen`, `sMaxMsgLenLobby` |
| rate limit | `sMinChatSendMS = 3000`; the send side blocks until `getTimer() - player.vwmTQz > kkrMwh` | `:3655`, `:3708` |
| allowed characters | `isLegalChatString` (`:51-68`) | letters, digits, ` !?,.@#$%^*()[]'"/\:;-=_|` |
| filter | `lqyRHh()` applied when `optionLanguageFilter` is on and the sender is not me | `:4964-4967` |
| filter data | `com/languagefilter.ini` | `:3516` |

`[C]` The lobby has a separate private-message button
(`sendChatMsgPrivate`, `:9019-9023`) which sends `00<uid>P<message>`; the server
relays it as `M<senderUID>P<message>` (`GenericSendDataHandler.java:58`) and
the client renders it in yellow with `privateMessage.wav`.

`[C]` VIP markers are ordinary chat messages `>VIP<` / `>UNVIP<` sent by the room
creator (`:4974-4995`), not a dedicated packet.

`[C]` The ignore list is client-side only (`ignoreList`, checked in
`remoteChatMsgLobby`, `:4958-4961`), toggled with `/ignore <name>`
(`ignoreUser`, `:7995-8038`). Ignored players can still be seen, they are only
muted locally.

## 7.5 Slash commands

`processSlashSyntaxCommand()` (`frame_1/DoAction.as:7655-7995`) implements the
client-side commands; the moderator ones map to packets:

| command | packet |
| --- | --- |
| `/find <name>` | `0h<name>` |
| `/ip <name>` | `07<uid>` |
| `/warn <uid> <msg>` | `0g<uid><msg>` |
| `/ban <name> <period> <msg>` | `0f<name>;<period>;<msg>` |
| `/kick` | `K<uid>` |
| `/report <uid> <code>` | `T<uid><code>` |
| `/ignore <name>` | local |
| `/filter`, `/faq`, `/eula`, `/rules`, `/mod?` | local UI / URL |

`[C]` `/ban` is sent as `0f` but the server's name-ban handler listens on `0l`
(`PacketHandlerLobby`), and `/report` sends `T`, which the server does not handle
at all — see `docs/protocol.md` §2 and [06](06-multiplayer-sync.md) §6.8.

## 7.6 Vote kick

| side | behaviour | source |
| --- | --- | --- |
| client send | `K<uid>` | `sendVoteKick`, `:9023-9027` |
| client receive | `M<uid>K<target>` → `vwPzUs` increments `voteKickVoteCount` | `:5037-5058` |
| client window | `sVoteKickDisplayTime = 10000` ms, disabled for `sVoteKickDisabledTime = 20000` ms | `sVoteKick*` |
| server tally | needs `> 1` votes **and** `>= clients - 1` | `StickRoom.java:238` |
| server effect | adds the target's DB id to the room blacklist, sends `getKickedPacket`, deregisters | `:239-242` |

`[C]` The server blacklist is per-room and per-`dbID`, so a kicked player cannot
rejoin that room (`NewClientHandler.java:86-89`).

## 7.7 Shop, inventory and lab pass

| action | packet | server handler |
| --- | --- | --- |
| list owned items | `0c` | `InventoryRequestHandler` → `getInventoryPacket` |
| buy | `0b<item:3><r0><g0><b0><r1><g1><b1>` | `BuyItemRequestHandler` (table `inventory`, `shop`) |
| set active | `0d<itemId>` | `SetActiveItemRequestHandler` |
| claim cred ticket | `0a` | `GiveTicketHandler` (`sTicket*`, 8 h cooldown) |

Item ids are offset by type: pets are `200 + n` (`NewClientHandler.java:108-110` pads `itemID - 200`), spinners are 0–99. Prices come from
`upgradevalues558.ini` (`analysis/upgradevalues558.json`), and the server keeps
its own `shop` table — the two are independent sources that must agree for the
client's displayed price to match what is charged.

## 7.8 Profile: spinners, pets, colours

`frame_4` (`profileFrame`) edits the player's cosmetics; the model is described in
[01](01-player.md) §1.5. `updateCustomizationArrows` / `selectCustomizationTab` /
`clearSpinnersCustomization` / `clearPetsCustomization` /
`updateCustomizationTopAnimation` (`frame_1/DoAction.as:8043-8134`) drive the
preview. Colours are chosen from `minPlayerColorValue`..`maxPlayerColorValue` and
sent with the next `U` packet.

## 7.9 Options

`optionsFrame` (frame 11) exposes `sOptionQuality`, `sOptionLanguageFilter`,
`sOptionParticles`, `sOptionBlood`, `sOptionCrosshair`, plus key rebinding
(`sK*`). Settings persist through a SharedObject named `xgenstickarenab`
(`savePreferences` `:3588`, `loadPreferences` `:3614`), not through the server.

## 7.10 Cross-reference: lobby packets

| client opcode | server handler | reply |
| --- | --- | --- |
| `01` | `RoomRequestHandler` | `01` room list |
| `02` | `CreateRoomHandler` | `01` + room detail |
| `03` | `NewClientHandler` | `C`/`U` sequence |
| `04` | `RoomDetailRequestHandler` | `04` |
| `06` | `MapCycleRequestHandler` | `06mp=` |
| `08` | `CheckCapacityHandler` | `08` or `09` error `0` |
| `09` | `LoginHandler` | `A` or `09` error |
| `0a` | `GiveTicketHandler` | `0a<amount>` |
| `0b` | `BuyItemRequestHandler` | `0c` inventory |
| `0c` | `InventoryRequestHandler` | `0c` |
| `0d` | `SetActiveItemRequestHandler` | `U` update |
| `0g` | `ModWarnHandler` | `0g<msg>` |
| `0f` | `ModBanHandler` | `0e`/`0f` ban notice |
| `0h` | `FindRequestHandler` | `0h<msg>` |
| `0i` | `MapRatingHandler` | — |
| `0j` | `ModGlobalHandler` | `0j<msg>` |
| `0m` | `ModKillRoomHandler` | `D` for each client |
| `9` | `GeneralChatHandler` | `M<uid>9<msg>` |

## 7.11 Open questions

- `[U]` `recieveError` handles `0`–`4` only; the server's `42` (room full / no
  lab pass) and `5` have no client branch, so the UI shows nothing specific.
- `[A]` The room-list flag byte meaning "needsPass" vs "isBallistick" suggests
  the server and client disagree on naming but not on behaviour; a non-lab-pass
  Ballistick room would expose the difference.
- `[U]` `com/languagefilter.ini` is loaded by both client and server
  (`GeneralChatHandler`); whether the two filter identically was not compared.
