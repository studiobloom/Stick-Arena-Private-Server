#!/usr/bin/env python3
"""
make_test_maps.py -- generate test-only copies of the 558 stock maps with a
single shared spawn point, so two clients reliably spawn on top of each other.

Why: quickstart spawns each client at `random(playerSpawnPoints)` (frame_1:
`stick.prototype.spawn`, `:9192`). With the shipped maps the two players land
far apart, so an attack test needs minutes of unreliable keyboard chasing.
Pointing all 8 `&sp=` slots at one author-chosen spawn makes the encounter
deterministic.

What is changed: only the `&sp=` section (8 x " x y" pairs). The tile grid,
weapon spawns, round time and tile set are copied byte-for-byte from the
original. Files are written under runtime/http/ so the harness serves them
instead of the repository copies; `htdocs/stickarena/maps/558/` is never
touched.

Usage:
  python runtime/harness/make_test_maps.py
"""

from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
REF = os.path.dirname(RUNTIME)
REPO = os.path.dirname(os.path.dirname(REF))
SRC = os.path.join(REPO, "htdocs", "stickarena", "maps", "558")
DST = os.path.join(RUNTIME, "http", "maps", "558")


def rewrite(path: str) -> str:
    raw = open(path, "rb").read().decode("latin-1")
    m = re.search(r"&sp=([^&]*)", raw)
    if not m:
        raise SystemExit("no &sp= section in %s" % path)
    pairs = re.findall(r"(-?\d+)\s+(-?\d+)", m.group(1))
    if not pairs:
        raise SystemExit("no spawn pairs in %s" % path)
    # keep the author's first spawn point, repeat it for all 8 slots
    x, y = pairs[0]
    section = "".join("%4s %4s " % (x, y) for _ in range(8))
    return raw[:m.start(1)] + section + raw[m.end(1):]


def main():
    made = 0
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".dat"):
            continue
        out_dir = DST
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, name)
        with open(out, "w", encoding="latin-1", newline="") as f:
            f.write(rewrite(os.path.join(SRC, name)))
        made += 1
    print("wrote %d test maps to %s" % (made, os.path.relpath(DST, REF)))
    print("only the &sp= section differs; originals untouched")


if __name__ == "__main__":
    main()
