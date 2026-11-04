# Scenario: combat (2 clients, deterministic overlap)

The harness served test copies of the stock maps with all 8 spawn slots pointing
at one tile (`make_test_maps.py`; only `&sp=` differs). Both clients therefore
spawn on the same spot, so a fist attack lands without any movement input.

Expected from source: the attacker sends `4`; the *victim* runs the hit test,
applies damage locally and emits `6` with the damage value; at 0 HP it emits `7`
and respawns 150 frames (~4.4 s) later.
