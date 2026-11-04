# 5. Health, death, respawn and scoring

Health is a single integer per client, damage is decided by the victim's client,
and kills/deaths are packed into integers so they can travel as short decimals.
Round outcomes are decided by leaderboard position, not by the server.

## 5.1 Health

| field | value | source |
| --- | --- | --- |
| current HP | `player.vwcSqZ` | `frame_1/DoAction.as:2864` |
| max HP | `player.qxCihK` = **60** | same line |
| damage | integer, `int(d)` | `:9078` |

`updateHPBar()` (`frame_1/DoAction.as:9067-9074`):

```actionscript
gfHcDRb.maskMC._x = -298 + this.vwcSqZ / this.qxCihK * 198;
heartNum = int(this.vwcSqZ / this.qxCihK * 3);
```

`[D]` The bar is a 198 px mask offset from −298, and the heart indicator is
`floor(hp/60 × 3)`, i.e. 3 hearts above 40 HP, 2 above 20, 1 above 0, 0 at death.
Hearts are clips `heart0MC` … `heart3MC` inside `gfHcDRb` (2906).

## 5.2 Damage application

`stick.prototype.damage(d, a, w, deg)` (`frame_1/DoAction.as:9074-9127`), in order:

1. no-op if `mod == "dead"`;
2. `d = int(d)`; if `d == 0` skip the effects but still update the bar;
3. `vwcSqZ -= d`;
4. effects: `damageFX` (`red = d*20`, `fade = d*6`), `shakeSAFX`
   (`xyMove = d/2`, `xyAcc = -max(d/6,1)`), HP-bar `shakeParentFX` and
   `damageHpFX` (`red = d*60`);
5. blood: `optionBlood²` clips of `blood<bloodAnim><random(bloodVariations)>MC`;
6. impact sound `SFX<attackAnim>Impact`;
7. `updateHPBar()`;
8. **`sendDamage(d, w, deg)`** → opcode `6` (`:8995-9003`);
9. if `vwcSqZ <= 0` → `tqkYQT(a, w, deg)`.

`[C]` Step 8 is why damage is victim-authoritative: the client that was hit tells
the room how much it lost.

## 5.3 Death

`tqkYQT(a, w, deg)` (`frame_1/DoAction.as:9127-9159`):

| action | detail |
| --- | --- |
| `qxwYxT(a, w, deg)` | broadcasts opcode `7` (killer id, weapon, angle) |
| `gotoAndStop("deathFrame")` | main timeline frame 10, unless `gameMode == 4` |
| `mod = "dead"` | stops movement, disables input |
| `deathFX`, hearts hidden, `heart0MC` frame 24 | |
| `animateDeath(...)` | corpse animation, direction and distance |
| `addToDeaths(1)`, `jhdIys = 0` | death counter, kill-streak reset |
| `setPetAnimation(..., "death")` | |

`animateDeath(mc, a, w, deg, kss, x, y)` (`:5859-5904`) picks the corpse frame and
the soul effect:

```actionscript
var radAngle = 3.141592653589793 / (180 * (deg + 270));
...
rnd = Math.max(random(2) + maxDistance, 1);
deathMC.gotoAndStop(rnd);
if(kss > 0) soulHellMC ... else soulHeavenMC ...
```

- `maxDistance` is found by probing `deathDistance[]` (an ini array) along the
  death direction against the collision layer, so a corpse stops at a wall
  (`:5865-5875`);
- `rnd` selects one of the 7 frames of `deathMC` (3249);
- `kss > 0` (at least one kill since the last death) sends the player to
  `soulHellMC` (3017, 58 frames), otherwise `soulHeavenMC` (3257, 52 frames).

`[C]` The angle formula is **not** the usual `deg × π/180`. The AVM1 P-code
confirms the operand order (`extracted/scripts/pcode/frame_1/DoAction.pcode`,
`DefineFunction "animateDeath"`):

```
Push "radAngle", 3.141592653589793, 180, "deg" ; GetVariable ; Push 270 ; Add2
Multiply ; Divide
```

i.e. `π / (180 × (deg + 270))`, which is ~0.000065 rad for `deg = 0`. The corpse
distance probe therefore almost always runs along +x. This is an original-code
quirk, preserved here rather than "fixed".

## 5.4 Respawn

| field | value | meaning |
| --- | --- | --- |
| `kkPTHf` / `kkEEBi` | **150** | frames until respawn (`:2886`) |
| `lqmKIZ` / `zqbcal` | **133.3** | frames of spawn protection (`:2887`) |

While `mod == "dead"`, `move()` decrements `kkPTHf` by
`max(1, int(frameDeltaTime/4/33.3))` (`:9485-9491`); at ≤ 0 it calls `spawn()`,
which resets HP, picks `random(playerSpawnPoints)`, broadcasts opcode `8` and
replays the spawn effect (`:9159-9201`).

`[D]` ≈ 4.4 s dead and ≈ 3.9 s protected at 34 fps.

> **Runtime check (2026-11-04).** 12 fist hits at 5 damage each = **60**, i.e.
> exactly the HP pool, produced one death packet and a respawn **4.38 s** after
> death (`runtime/evidence/combat/result.json`) — the predicted 150 frames /
> 34 fps = 4.41 s. The test waited 5 s after spawn before attacking, so spawn
> protection (`jhIqSQ`) was already over; the protection window itself is still
> unverified.

## 5.5 Score and death packing

Kills and deaths are stored as scaled integers, presumably so they can be printed
with `pad()` into fixed-width fields without floats:

```actionscript
addToScore(p)  { this.lqexbO = (this.getScore() + p) * 13 + 11; ... }
getScore()     { return (this.lqexbO - 11) / 13; }
addToDeaths(p) { this.jhSfVJ = (this.getDeaths() + p) * 11 + 13; ... }
getDeaths()    { return (this.jhSfVJ - 13) / 11; }
```

— `frame_1/DoAction.as:9047-9067`. `jhdIys` is the kill streak (reset on death),
used for the hell/heaven choice and for the "kills since spawn" bonus display.

`[A]` The odd constants (13/11 and 11/13) look like a deliberate obfuscation or a
leftover from an older serialisation; no other code depends on them.

## 5.6 Leaderboard position

`getPosition(s, dt)` (`frame_1/DoAction.as:5838-5859`):

```actionscript
position = 1;
for each remote player:
   if(kills > s || kills == s && jhSfVJ < dt) position++;
position = Math.min(position, playerCount);
```

So rank 1 = most kills, ties broken by **fewer deaths**. `updatePositionDisplay`
(`:9031-9047`) shows `posText[position]` and plays `positionFirst.wav` when
reaching rank 1.

The in-game leaderboard (`B` key) is `displayLeaderBoard()` /
`updateLeaderBoard()` (`:6491-6698`) and is also forced on when dead with
`kkPTHf <= 90` (`updateHUDDead`, `:817-834`).

## 5.7 Round end

`endRound()` (`frame_1/DoAction.as:7000-7049`):

```actionscript
player.vwFidm   += player.getScore();     // lifetime kills accumulator
player.pDeaths  += player.getDeaths();
if(getPosition(player.getScore(), player.getDeaths()) == 1) player.pWins++;
else                                                        player.pLosses++;
_root.attachMovie("summaryBoardMC","sumMC",200002);
clearGameGarbage();
displaySummaryScoresAnims();
gotoAndStop("roundSummaryFrame");
```

`[C]` "Win" is therefore *finishing first in this room*, not "your team won";
with 6 players there is exactly one winner per round.

`startNextRound(firstRound)` (`:7049-7091`) then rotates the map cycle, resets
round variables and goes to `preMain`.

## 5.8 Round timing

| value | source |
| --- | --- |
| `sRoundTime` = **300 s** | `settings558b.ini`, read at `:3401` |
| `sSummaryTime` = **11 s** | `:3402` |
| `sAdTime` = **20 s** | `:3403` |
| `tqJqPc = roundTime + summary + ad` | `:7064` |

`updateRoundTimer()` (`:3104-3138`) runs once per second (interval set in
`enterArea`), decrements `tqJqPc`, re-syncs from the server when it has drifted
more than 15 s (`sendRoomDetailRequest(..., "updateRoundTime")`), announces
`timeNotify[]` thresholds and calls `endRound()` at ≤ 0.

`[C]` The server's `getSendRoundDetail` sends `RoundTime + 31`
(`Tools/StickPacketMaker.java:101`) and the client subtracts `summary + ad`
(`recieveRoomDetail`, `:5205`) — and 11 + 20 = **31** exactly. That is a direct
client/server contract, not a coincidence.

## 5.9 Cross-reference: the server

| server behaviour | value | source |
| --- | --- | --- |
| round timer | `RoundTime = 300`, −1 per second | `Types/StickRoom.java:74,259` |
| stats update | at `RoundTime == -1` → `updateStats(getWinner())` | `:260-262` |
| reset | at `RoundTime <= -30` → `RoundTime = 300` | `:263-265` |
| winner | client with the most `gameKills` | `:288-330` |
| rounds counter | `UPDATE users SET rounds = rounds + 1` for every joined name | `:266-285` |
| kill tracking | `KillHandler` increments `gameKills` on opcode `7` | `Game/handlers/KillHandler.java` |

`[C]` The server's round ends 301 s after the room starts and then waits 30 s
before resetting, while the client expects `roundTime + summary + ad` = 331 s.
The 1 s difference (301 vs 331−30) and the meaning of the extra window are worth
observing at runtime — see [08](08-runtime-verification.md) item 5.

## 5.10 Open questions

- `[U]` `updateStats(getWinner())` is called once at `RoundTime == -1`; what it
  writes (wins/losses per client) was not traced beyond the `rounds` counter.
- `[A]` The client's `pWins`/`pLosses` are accumulated locally and only sent to
  the web tier via `stick_arena.php` `action=round_stats` (which the 558 SWF does
  **not** call — see `docs/architecture.md` §3), so in a 558-only server the
  persistent win/loss stats are updated by the server's own `updateStats`, not by
  the client.
- `[U]` `deathDistance[]` values come from `settings558b.ini`; the shipped array
  was not transcribed.
