# Scenario: movement (1 client)

Each direction is held 2.2 s in run mode, then 2.2 s in walk mode (`V`), and the
best free run is kept. Speeds are read from the client's own `1` position packets
(`xVel*1000`, `yVel*1000`), so walls only remove samples, they cannot inflate them.

Source prediction (`docs/systems/02-movement-collision.md`): run ~4.9 px/frame
(~167 px/s), walk ~2.2 px/frame (~75 px/s).
