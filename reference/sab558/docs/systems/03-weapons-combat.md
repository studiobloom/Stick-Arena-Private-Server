# 3. Weapons, pickups, attacks and damage

Fourteen weapon slots (`0`–`13`) are declared in one table in the client. Two of
them are the same fist, one (`knife`) exists only as an unused animation, and the
damage model is **victim-side**: the attacker broadcasts, every other client
decides whether its own player was hit.

## 3.1 The weapon table

`initializeWeapons()` — `frame_1/DoAction.as:1823-1839` — builds
`weapons[0..13]` from `weaponType(...)` (`:1841-1859`). Decoded by
`scripts/build_systems_index.py` into `analysis/systems/weapons.json`:

| id | anim | damage | cooldown | ranged | walk speed | blood | variants | death rot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `fist` | 5 | 17 → 561 ms | no | 1.0 | — | 3 | 0° |
| 1 | `fist` | 5 | 17 → 561 ms | no | 1.0 | — | 3 | 0° |
| 2 | `bat` | 19 | 20 → 660 ms | no | 0.9 | `Bat` ×2 | 1 | 45° |
| 3 | `sword` | 8 | 12 → 396 ms | no | 1.0 | `Sword` ×1 | 3 | 30° |
| 4 | `glock` | 13 | 18 → 594 ms | **yes** | 0.8 | `Bullet` ×3 | 1 | 0° |
| 5 | `ak47` | 11 | 14 → 462 ms | **yes** | 0.7 | `Bullet` ×3 | 3 | 0° |
| 6 | `shotgun` | 20 | 40 → 1320 ms | **yes** | 0.7 | `Shotgun` ×3 | 1 | 0° |
| 7 | `sledge` | **80** | 65 → 2145 ms | no | 0.7 | `Sword` ×1 | 1 | 0° |
| 8 | `flamethrower` | 11 | 15 → 495 ms | **yes** | 0.75 | — | 1 | 0° |
| 9 | `railgun` | 50 | 80 → 2640 ms | **yes** | 0.65 | `Shotgun` ×3 | 1 | 0° |
| 10 | `chainsaw` | 21 | 22 → 726 ms | no | 0.8 | `Sword` ×1 | 3 | 0° |
| 11 | `lasersword` | 10 | 15 → 495 ms | no | 1.0 | — | 3 | 30° |
| 12 | `helmet` | 6 | 13 → 429 ms | no | 0.9 | — | 1 | 0° |
| 13 | `chaingun` | 9 | 11 → 363 ms | **yes** | 0.7 | `Bullet` ×3 | 1 | 0° |

`cooldown = qxdMlq × 33 ms` (`frame_1/DoAction.as:9250`). `[D]` Damage per second
if every hit lands: sledge 37.3, chainsaw 28.9, bat 28.8, chaingun 24.8, ak47
23.8, flamethrower 22.2, glock 21.9, sword/lasersword 20.2, railgun 18.9, shotgun
15.2, helmet 14.0, fist 8.9. **HP is 60**, so a single sledge hit kills.

Field meanings, from the constructor (`frame_1/DoAction.as:1841-1859`):

| field | meaning | used at |
| --- | --- | --- |
| `attackAnim` | label prefix for attack animation and sounds | `:9247`, `:4085` |
| `idleAnim` / `runAnim` | label prefixes for the two idle poses | `:6065`, `:6088` |
| `bloodAnim` / `bloodVariations` | blood clip name and variant count | `:4186` |
| `particleAnim` / `particleAnimLow` | **booleans**: emit particles at all / use the low-quality clip | `:5904-5922` |
| `automatic` | hold-to-repeat (always `true` in this build) | `:9266` |
| `range` | ranged weapon → projectile raycast | `:4119` |
| `damage` | integer HP subtracted | `:4145` |
| `qxdMlq` | cooldown in 33 ms units | `:9250` |
| `walkingSpeed` | multiplier on acceleration and max speed | `:5956` |
| `variations` | number of `Attack1..N` variants | `:4073` |
| `deathRotation` | degrees added to the death animation angle | `:4145` |

`[C]` The `variations` field is validated against the animation table: every one
of the 14 weapons has exactly `variations` `AttackN` labels in `gfoKHPq`
(`analysis/systems/weapons.json` → `variants_field_matches_table`, all `true`).

`[C]` `automatic` is `true` for all 14 weapons, so the semi-automatic branch in
`autoAttack()` (`frame_1/DoAction.as:9264-9274`) never applies in this build; the
`mouseUp` handler that re-arms `zqyafO` (`frame_9/…onClipEvent(mouseUp).as:2`) is
therefore dead code for these weapons.

## 3.2 Attack flow

Local attack — `qkZPDc()` (`frame_1/DoAction.as:9230-9264`):

1. if `kkwrFk != 0` (cooldown active) do nothing; otherwise
2. `sendAttack()` → opcode `4` (`:8978-8989`);
3. `gfoKHPq.gotoAndStop(<attackAnim> + "Attack" + rnd)` with
   `rnd = random(variations) + 1`;
4. `gfoKHPq.gxfpoCYV.gotoAndPlay(1)` starts the hit-area animation;
5. particles (`attachParticles`) and the attack sound;
6. `kkwrFk = qxdMlq * 33` and `currentRoundWeaponAttacks[w]++`;
7. if the weapon is not the fist, `zqbcal = 0` (spawn protection ends
   immediately); with the fist, `zqbcal -= 33.3`.

The animation ends by calling `player.doneAttack()` from the clip's last frame —
one clip per variant, e.g. `DefineSprite_1783/frame_13/DoAction.as:1`. That is
the only thing that resets `vzeCpU` and returns the arm to its idle pose
(`frame_1/DoAction.as:9274-9286`).

`[C]` Attack animation length and cooldown are **independent**, and for most
weapons the cooldown is shorter than the animation:

| weapon | animation | length | cooldown | consequence |
| --- | --- | --- | --- | --- |
| sword | `swordAttack1` (1893) | 1.41 s | 0.40 s | next attack interrupts the swing |
| flamethrower | `flamethrowerAttack1` (2150) | 2.21 s | 0.50 s | heavily interrupted |
| chaingun | `chaingunAttack1` (2229) | 1.32 s | 0.36 s | heavily interrupted |
| shotgun | `shotgunAttack1` (1984) | 0.85 s | 1.32 s | 0.47 s idle between shots |
| sledge | `sledgeAttack1` (2073) | 2.21 s | 2.15 s | animation ≈ cooldown |
| railgun | `railgunAttack1` (2529) | 2.00 s | 2.64 s | 0.64 s idle |
| fist | `fistAttack1` (1783) | 0.38 s | 0.56 s | 0.18 s idle |

`[U]` Because the hit test happens when the attack is broadcast (not on a
specific animation frame), the visible swing and the damage moment can be up to
one network round-trip apart.

## 3.3 Hit detection

`qxTtuh(a, w)` (`frame_1/DoAction.as:4098-4160`) runs on every client that
receives someone else's attack:

```actionscript
with(eval("xqXvQHh.player" + a + "MC")) {           // the attacker's clip
   var distance = Math.pow(_x + xqXvQHh._x - xx,2) + Math.pow(_y + xqXvQHh._y - yy,2);
   if(distance < 250000) {                            // <= 500 px
      if(weapons[w].range || distance < 10000) {      // melee: <= 100 px
         if(gfoKHPq.gxfpoCYV.fqgFvkCAnev.hitTest(xx,yy,true) || ... ±6 ...) {
```

- `xx, yy` is the **local** player's position (`gxqKQk`, or
  `xqXvQHh.player<myid>MC` when `collisionCheckGhost` is on, `:4102-4110`);
- the hit area is the attacker's `gxfpoCYV.fqgFvkCAnev` child, probed at the
  target centre and at four ±6 px offsets (`:4121`);
- ranged weapons skip the 100 px melee gate; melee weapons skip the raycast.

For ranged weapons the client then walks a ray from the attacker toward the
target in **10 px** steps, starting after a **30 px** gun length, and stops if it
enters a tile whose collision type is `3` (`:4128-4146`):

```actionscript
while(hitDistance < distance - gunLength) {
   xHit = int(xx + Math.cos(radAngle) * hitDistance);
   yHit = int(yy + Math.sin(radAngle) * hitDistance);
   xTileHit = int((xHit - xqXvQHh._x) / 50 + 0.5);
   yTileHit = int((yHit - xqXvQHh._y) / 50 + 0.5);
   if(earth[xTileHit][yTileHit][3] == 3) { collision = true; hitDistance = distance; }
   hitDistance += resolution;
}
```

So walls block bullets only where the map author used collision type 3; types
4/5–9 do not stop projectiles even though they block movement.

`[C]` Hit detection is skipped entirely when the attacker is the local player:
`kkXcpL` only calls `qxTtuh` inside `if(textMC.localIdText.text != 0)`
(`frame_1/DoAction.as:4079`). `localIdText` is the slot number, `0` for the local
player (`addPlayer`, `:3865`). This is what prevents a client from damaging
itself with its own echo.

## 3.4 Damage

`stick.prototype.damage(d, a, w, deg)` (`frame_1/DoAction.as:9074-9127`):

1. ignored if already `dead`;
2. `d = int(d)`; `vwcSqZ -= d` (HP, max 60);
3. visual feedback: `damageFX` red `d*20`, fade `d*6`; `shakeSAFX` `xyMove = d/2`,
   `xyAcc = -max(d/6,1)`; HP-bar shake; `damageHpFX` red `d*60`;
4. blood particles: `optionBlood²` clips named `blood<bloodAnim><random(bloodVariations)>MC`,
   random rotation/scale;
5. `adjustAndPlaySound(SFX<attackAnim>Impact[0])`;
6. `updateHPBar()`, then **`sendDamage(d,w,deg)`** → opcode `6`;
7. if HP ≤ 0 → `tqkYQT()` (death, see [05](05-health-death-scoring.md)).

`[C]` The victim's client is the authority: it subtracts HP and broadcasts the
damage. The attacker's client never applies damage to anyone.

> **Runtime check (2026-11-04, Ruffle 0.7.1).** Two clients on a shared spawn
> tile: the attacker sent 16 `4` packets, and **all 12 damage packets came from
> the victim's uid** (`003 6 05 0 359`), each carrying damage **5** — the fist
> value from the weapon table. The attacker sent no `6` packet. The victim's
> screen showed the kill message from the ini's `sKillTextPre/Post` table
> (`runtime/evidence/combat/`). This confirms §3.3/§3.4 end to end.

## 3.5 Pickups and respawn timers

`updateWeaponSpawns()` (`frame_1/DoAction.as:6172-6199`) runs every 4th frame
(`onFrame`, `:2937`):

| step | behaviour |
| --- | --- |
| timer > 0 | `vwTmZM -= frameDeltaTime` (ms) |
| timer ≤ 0 and player overlaps pickup and `w != player.qkUfJI` | `qxCsEe(w, i)`, remove clip, `vwTmZM = delay` |
| timer ≤ 0 and no clip | `spawnWeapon(i, w, x, y)` |

`qxCsEe(w, n)` (`:9208-9230`) switches the weapon, sends opcode `5`, shows the
HUD weapon icon, and shortens spawn protection by 66.6 frames when `w > 0`.

Pickup art (`pickup<attackAnim>MC`, `spawnWeapon` at `:6199-6209`):

| weapon | id | weapon | id |
| --- | --- | --- | --- |
| `pickupfistMC` | 4350 | `pickupchaingunMC` | 6209 |
| `pickupbatMC` | 4351 | `pickupchainsawMC` | 6210 |
| `pickupswordMC` | 4343 | `pickupflamethrowerMC` | 6211 |
| `pickupglockMC` | 4348 | `pickuplaserswordMC` | 6212 |
| `pickupak47MC` | 4352 | `pickuprailgunMC` | 6213 |
| `pickupshotgunMC` | 4345 | `pickuphelmetMC` | 6214 |
| `pickupsledgeMC` | 4344 | `pickupknifeMC` | 4347 (unused: no knife weapon) |

Pickups bob and spin: `y = sin(wave)*4 - 12`, shadow scale
`110 + sin(wave+π)*3.5`, alpha `23 + sin(wave)*6`, `wave += 0.1` per frame
(`animateWeaponPickups`, `:6209-6256`). They are only visible within
`|x-275| < 325` and `|y-200| < 250` of the viewport centre.

## 3.6 Sounds

`initializeSound()` (`:1861-2019`) and `initializeSoundBallistick()`
(`:2040-2109`) create one `Sound` object per player slot per effect, attached by
export name. `analysis/systems/sounds.json` maps all 73 referenced names to
character ids.

`[C]` Seven names cannot resolve as written:

| `attachSound()` name | situation | id of the real symbol |
| --- | --- | --- |
| `shotgun00.wav` | export is `Shotgun00.wav` (case differs) | 5279 |
| `ak47imp00.wav` | export is `AK47imp00.wav` | 5311 |
| `sledgeimp00.wav` | export is `Sledgeimp00.wav` | 5275 |
| `Sledgepick00.wav` | export is `sledgepick00.wav` | 5274 |
| `dragVolume.wav` | **no matching export at all** | — |
| `flamethrowerimp00.wav` | **no matching export at all** | — |
| `railgunimp00.wav` | **no matching export at all** | — |

`[U]` Flash linkage identifiers are case-sensitive, so the four case mismatches
should fail silently at runtime (the weapon would fire without its sound). The
three absent names mean the Ballistick flamethrower and railgun have no impact
sound defined in the SWF at all. Both need runtime confirmation — see
[08](08-runtime-verification.md) item 2.

## 3.7 Kill messages

Kill text is per weapon and comes from the ini, not the SWF: the client reads
`sKillTextPre<NN><n>` / `sKillTextPost<NN><n>` for weapon `NN`
(`frame_1/DoAction.as:3495-3508`) and picks `random(killTextNum)`
(`:5073`). `killTextNum` is the number of variants found.

## 3.8 Cross-reference: the server's role

| packet | server action |
| --- | --- |
| `4` (attack) | relayed to the room, unchanged (`GamePacketBroadcastHandler.java:30`) |
| `5` (weapon pickup) | relayed |
| `6` (damage) | relayed |
| `7` (death) | `KillHandler` updates the killer's kill counter and re-broadcasts |
| `K` (vote kick) | `VoteKickHandler` + `StickRoom.kickVote` |

`[C]` The server never validates damage, range or line of sight. A client can
claim any damage value; the only limit is the 2-character field width
(`pad(d,2)`, `:8998`).

## 3.9 Open questions

- `[U]` `vzXFhy(w)` (`:1703-1720`) gates `kkXcpL`; it appears to validate the
  weapon id, but its exact rule (range check? table lookup?) was not traced.
- `[A]` The two fist slots (0 and 1) look like a placeholder for "no weapon"
  versus "fist"; the code treats them identically.
- `[U]` `pickupknifeMC` (4347) and the `knifeAttack1` label (frame 9 of 2530)
  exist but no weapon entry references them — leftover from an earlier build.
