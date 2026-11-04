#!/usr/bin/env python3
"""
run_scenario.py -- drive the original 558 client under Ruffle against the local
harness and collect evidence.

This is the automated part of the runtime verification backlog. It does not
invent behaviour: it starts the real `sab558.swf`, sends real keyboard input,
captures the real window, and reads the real packets the client sent.

Scenarios
  login-lobby     title screen -> login form -> lobby        (1 client)
  quickstart      auto quickstart -> in-game                 (1 client)
  movement        hold a direction, measure speed from the `1` packets
  collision       run into a wall, look for velocity sign flips
  two-clients     two clients in the same room, one attacks  (2 clients)
  round-timer     observe the round clock and the `04` sync  (1 client)

Outputs (all under runtime/evidence/<scenario>/):
  shot_*.png      window captures (PrintWindow, see capture_window.ps1)
  packets.log     the harness packet log for this scenario
  result.json     parsed observations (packets, timings, derived numbers)
  notes.md        human summary of what was run

Usage
  python runtime/harness/run_scenario.py <scenario> [--seconds N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)
REF = os.path.dirname(RUNTIME)
REPO = os.path.dirname(os.path.dirname(REF))
RUFFLE = os.path.join(RUNTIME, "tools", "ruffle", "ruffle.exe")
STATE = os.path.join(RUNTIME, "state")
EVID = os.path.join(RUNTIME, "evidence")
WEB_OVERLAY = os.path.join(RUNTIME, "http")
PS = ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
SETTINGS = os.path.join(REPO, "htdocs", "stickarena", "settings558b.ini")


# --------------------------------------------------------------------------
def free_ports(port=1138, http_port=80):
    for p in (port, http_port):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
        finally:
            s.close()


def write_overlay(auto_quickstart: bool, no_perf_watchdog: bool = False,
                  skip_intro: bool = None):
    """Serve a test-time settings file. Only documented switches are changed."""
    os.makedirs(WEB_OVERLAY, exist_ok=True)
    src = open(SETTINGS, encoding="utf-8", errors="replace").read()
    out = src.replace("&sAutoQuickStart=0&", "&sAutoQuickStart=%d&" % (1 if auto_quickstart else 0))
    if skip_intro is None:
        skip_intro = auto_quickstart
    out = out.replace("&sSkipIntro=0&", "&sSkipIntro=%d&" % (1 if skip_intro else 0))
    if no_perf_watchdog:
        # PrintWindow stalls the GPU renderer for a moment; the client's own
        # checkPerformance() then sees <12 fps and boots to title after 15 s.
        # The watchdog is not what a long-timer test is measuring, so it is the
        # only other switch turned off, and only for that scenario.
        out = out.replace("&sEnforcePerformance=1&", "&sEnforcePerformance=0&")
    with open(os.path.join(WEB_OVERLAY, "settings558b.ini"), "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    return out != src


class Harness:
    def __init__(self, log_path):
        self.log_path = log_path
        self.proc = None

    def start(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        open(self.log_path, "w", encoding="utf-8").close()
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "stub_server.py"), "--log", self.log_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", 1138), 0.2).close()
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("harness did not start")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Client:
    def __init__(self, name, scenario_dir):
        self.name = name
        self.dir = os.path.join(scenario_dir, "client_" + name)
        self.proc = None

    def start(self, url="http://127.0.0.1/sab558.swf"):
        for sub in ("lso", "config", "cache"):
            os.makedirs(os.path.join(self.dir, sub), exist_ok=True)
        self.proc = subprocess.Popen([
            RUFFLE, "--width", "560", "--height", "420", "--volume", "0",
            "--tcp-connections", "allow", "--socket-allow", "127.0.0.1:1138",
            "--save-directory", os.path.join(self.dir, "lso"),
            "--config", os.path.join(self.dir, "config"),
            "--cache-directory", os.path.join(self.dir, "cache"),
            url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self

    def wait_window(self, timeout=60):
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = subprocess.run(PS + [os.path.join(HERE, "capture_window.ps1"),
                                     "-ProcId", str(self.proc.pid),
                                     "-Out", os.path.join(self.dir, "probe.png")],
                               capture_output=True, text=True)
            if r.returncode == 0 and "PrintWindow" in r.stdout:
                return True
            time.sleep(1)
        return False

    def keys(self, press=None, down=None, up=None, text=None):
        cmd = PS + [os.path.join(HERE, "send_keys.ps1"), "-ProcId", str(self.proc.pid)]
        for k in (press or []):
            cmd += ["-Press", k]
        for k in (down or []):
            cmd += ["-Down", k]
        for k in (up or []):
            cmd += ["-Up", k]
        if text:
            cmd += ["-Type", text]
        return subprocess.run(cmd, capture_output=True, text=True)

    def shot(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        r = subprocess.run(PS + [os.path.join(HERE, "capture_window.ps1"),
                                 "-ProcId", str(self.proc.pid), "-Out", path,
                                 "-MaxWidth", "1024"],
                           capture_output=True, text=True)
        return r.returncode == 0 and os.path.exists(path)

    def stop(self):
        if self.proc:
            subprocess.run(["taskkill", "/F", "/PID", str(self.proc.pid)],
                           capture_output=True)


# --------------------------------------------------------------------------
def read_packets(path):
    out = []
    if not os.path.exists(path):
        return out
    pat = re.compile(r"^(\d\d:\d\d:\d\d\.\d\d\d) (\S+)\s+(.*)$")
    for line in open(path, encoding="utf-8", errors="replace"):
        m = pat.match(line.rstrip("\n"))
        if not m:
            continue
        out.append({"t": m.group(1), "kind": m.group(2), "detail": m.group(3)})
    return out


def to_seconds(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_positions(packets, uid):
    """Decode opcode-1 position packets from one client (client -> server)."""
    rows = []
    for p in packets:
        if p["kind"] != "C->S" or not p["detail"].startswith(uid + " 1"):
            continue
        body = p["detail"][len(uid) + 1:]
        if len(body) < 28 or body[0] != "1":
            continue
        try:
            x = int(body[1:6]) / 10.0
            y = int(body[6:11]) / 10.0
            facing = body[11:13]
            moving = body[13]
            walk = body[14]
            xv = int(body[15:20]) / 1000.0
            yv = int(body[20:25]) / 1000.0
            rot = int(body[25:28])
        except ValueError:
            continue
        rows.append({"t": to_seconds(p["t"]), "x": x, "y": y, "facing": facing,
                     "moving": moving, "walk": walk, "xv": xv, "yv": yv, "rot": rot})
    return rows


def uid_for_pid(pid, packets_path, timeout=40):
    """Map this Ruffle process to the uid the harness assigned it.

    Works by matching the process's established TCP local port against the
    harness log's "connect ('127.0.0.1', <port>)" line, so other clients
    (including a human playtesting on the same machine) cannot be confused
    with the automated one.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        ports = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            if parts[0] != "TCP" or parts[3] != "ESTABLISHED":
                continue
            if parts[4] != str(pid):
                continue
            if not parts[2].endswith(":1138"):
                continue
            ports.add(parts[1].rsplit(":", 1)[-1])
        if ports:
            for rec in read_packets(packets_path):
                if rec["kind"] != "EVENT":
                    continue
                m = re.search(r"connect \('127\.0\.0\.1', (\d+)\) \(assigned uid (\d+)\)",
                              rec["detail"])
                if m and m.group(1) in ports:
                    return m.group(2)
        time.sleep(0.5)
    return None


def scenario_dir(name):
    d = os.path.join(EVID, name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    return d


def save_result(d, obj):
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def notes(d, text):
    with open(os.path.join(d, "notes.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text.strip() + "\n")


# --------------------------------------------------------------------------
def sc_quickstart(args):
    d = scenario_dir("quickstart")
    write_overlay(auto_quickstart=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    c = Client("A", d).start()
    try:
        assert c.wait_window(), "no Ruffle window"
        shots = []
        for i, delay in enumerate((6, 6, 6, 6)):
            time.sleep(delay)
            p = os.path.join(d, "shot_%02d.png" % i)
            if c.shot(p):
                shots.append(os.path.basename(p))
        pk = read_packets(os.path.join(d, "packets.log"))
        uids = sorted({p["detail"][:3] for p in pk if p["kind"] == "C->S"})
        res = {
            "scenario": "quickstart",
            "client_ran": True,
            "uids": uids,
            "screenshots": shots,
            "packet_counts": {},
            "first_packets": [p["detail"] for p in pk if p["kind"] == "C->S"][:12],
        }
        for p in pk:
            if p["kind"] == "C->S" and len(p["detail"]) > 4:
                op = p["detail"][4:5]
                res["packet_counts"][op] = res["packet_counts"].get(op, 0) + 1
        save_result(d, res)
        notes(d, """
# Scenario: quickstart (1 client)

Config overlay: `sAutoQuickStart=1`, `sSkipIntro=1` (only those two dev switches
differ from `htdocs/stickarena/settings558b.ini`).

The client was launched under Ruffle against the local harness and left to run.
Screenshots are PrintWindow captures of the Ruffle window; `packets.log` is the
harness wire log.
""")
    finally:
        c.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_movement(args):
    d = scenario_dir("movement")
    write_overlay(auto_quickstart=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    c = Client("A", d).start()
    try:
        assert c.wait_window(), "no Ruffle window"
        # wait until the client is in game (spawn packet 8 seen)
        t0 = time.time()
        while time.time() - t0 < 60:
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 8", p["detail"]) for p in pk):
                break
            time.sleep(1)
        time.sleep(1.5)
        c.shot(os.path.join(d, "shot_idle.png"))

        def reset_keys():
            c.keys(up=["RIGHT", "LEFT", "UP", "DOWN", "V", "SPACE", "B"])

        def hold(keys, secs):
            for k in keys:
                c.keys(down=[k])
            time.sleep(secs)
            for k in keys:
                c.keys(up=[k])
            time.sleep(0.35)

        uid = uid_for_pid(c.proc.pid, os.path.join(d, "packets.log"))

        # Walls can hide the speed plateau, so probe every direction in both
        # modes and keep the best free run. V is the walk binding (sKWalk0=118).
        for mode, extra in (("run", []), ("walk", ["V"])):
            for direction in ("RIGHT", "LEFT", "UP", "DOWN"):
                reset_keys()
                hold([direction] + extra, 2.2)
        c.shot(os.path.join(d, "shot_after_probe.png"))

        pk = read_packets(os.path.join(d, "packets.log"))
        pos = parse_positions(pk, uid)
        moving = [p for p in pos if p["moving"] == "1"]

        def best(mode):
            sel = [p for p in moving if p["walk"] == ("1" if mode == "walk" else "0")]
            if not sel:
                return None
            speeds = sorted(((p["xv"] ** 2 + p["yv"] ** 2) ** 0.5 for p in sel))
            return {
                "samples": len(sel),
                "max_px_per_frame": round(speeds[-1], 3),
                "p95_px_per_frame": round(speeds[int(len(speeds) * 0.95) - 1], 3),
                "max_px_per_s": round(speeds[-1] * 34, 1),
            }

        run = best("run")
        walk = best("walk")
        res = {
            "scenario": "movement",
            "uid": uid,
            "position_packets": len(pos),
            "moving_samples": len(moving),
            "run": run,
            "walk": walk,
            "note": "speed = |(xVel,yVel)| in px per client frame; px/s = x34 fps",
        }
        save_result(d, res)
        notes(d, """
# Scenario: movement (1 client)

Each direction is held 2.2 s in run mode, then 2.2 s in walk mode (`V`), and the
best free run is kept. Speeds are read from the client's own `1` position packets
(`xVel*1000`, `yVel*1000`), so walls only remove samples, they cannot inflate them.

Source prediction (`docs/systems/02-movement-collision.md`): run ~4.9 px/frame
(~167 px/s), walk ~2.2 px/frame (~75 px/s).
""")
    finally:
        c.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_collision(args):
    d = scenario_dir("collision")
    write_overlay(auto_quickstart=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    c = Client("A", d).start()
    try:
        assert c.wait_window(), "no Ruffle window"
        t0 = time.time()
        while time.time() - t0 < 60:
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 8", p["detail"]) for p in pk):
                break
            time.sleep(1)
        time.sleep(1.0)
        # run left for 4 s into whatever is there, then right for 4 s
        c.keys(down=["LEFT"])
        time.sleep(4.0)
        c.shot(os.path.join(d, "shot_left_wall.png"))
        c.keys(up=["LEFT"])
        time.sleep(0.3)
        c.keys(down=["RIGHT"])
        time.sleep(4.0)
        c.shot(os.path.join(d, "shot_right_wall.png"))
        c.keys(up=["RIGHT"])
        time.sleep(0.5)
        uid = uid_for_pid(c.proc.pid, os.path.join(d, "packets.log"))
        pk = read_packets(os.path.join(d, "packets.log"))
        pos = parse_positions(pk, uid) if uid else []
        sign_flips = 0
        for a, b in zip(pos, pos[1:]):
            if a["xv"] * b["xv"] < 0:
                sign_flips += 1
        res = {
            "scenario": "collision",
            "position_packets": len(pos),
            "velocity_sign_flips": sign_flips,
            "min_x": min((r["x"] for r in pos), default=None),
            "max_x": max((r["x"] for r in pos), default=None),
            "max_abs_xv": max((abs(r["xv"]) for r in pos), default=None),
        }
        save_result(d, res)
        notes(d, """
# Scenario: collision (1 client)

Left held 4 s, then right held 4 s. A wall contact should show the client's own
velocity reversing (`jhzeUQ` does `xVel *= -0.5`), which is visible as a sign
change in consecutive `1` packets.
""")
    finally:
        c.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_two_clients(args):
    d = scenario_dir("two-clients")
    write_overlay(auto_quickstart=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    a = Client("A", d).start()
    try:
        assert a.wait_window(), "no Ruffle window A"
        # wait for A to create a room
        t0 = time.time()
        room = None
        while time.time() - t0 < 60:
            pk = read_packets(os.path.join(d, "packets.log"))
            for p in pk:
                if p["kind"] == "C->S" and " 02" in p["detail"]:
                    room = p["detail"].split(" 02")[1][4:]
                    break
            if room:
                break
            time.sleep(0.5)
        time.sleep(3)
        # any key dismisses the "having difficulty playing?" control-help overlay
        a.keys(press=["RETURN"])
        time.sleep(1.0)
        a.shot(os.path.join(d, "shot_A_before_B.png"))

        b = Client("B", d).start()
        assert b.wait_window(), "no Ruffle window B"
        time.sleep(6)
        b.keys(press=["RETURN"])
        time.sleep(3)
        a.shot(os.path.join(d, "shot_A_with_B.png"))
        b.shot(os.path.join(d, "shot_B_joined.png"))

        # A attacks a few times (space), then both move
        for _ in range(3):
            a.keys(press=["SPACE"])
            time.sleep(0.6)
        a.shot(os.path.join(d, "shot_A_attack.png"))
        a.keys(down=["RIGHT"])
        b.keys(down=["LEFT"])
        time.sleep(2.0)
        a.keys(up=["RIGHT"])
        b.keys(up=["LEFT"])
        time.sleep(0.5)
        a.shot(os.path.join(d, "shot_A_after_move.png"))
        b.shot(os.path.join(d, "shot_B_after_move.png"))

        pk = read_packets(os.path.join(d, "packets.log"))
        uids = sorted({p["detail"][:3] for p in pk if p["kind"] == "C->S"})
        ops = {}
        for p in pk:
            if p["kind"] == "C->S" and len(p["detail"]) > 4:
                op = p["detail"][4]
                ops[op] = ops.get(op, 0) + 1
        joined = [p["detail"] for p in pk if p["kind"] == "EVENT" and "join uid" in p["detail"]]
        res = {
            "scenario": "two-clients",
            "room": room,
            "uids": uids,
            "joins": joined,
            "packet_counts": ops,
            "server_sent_C": sum(1 for p in pk if p["kind"] == "S->C" and " C" in p["detail"]),
            "server_sent_U": sum(1 for p in pk if p["kind"] == "S->C" and " U" in p["detail"]),
        }
        save_result(d, res)
        notes(d, """
# Scenario: two clients in one match

Client A auto-quickstarts and creates a room. Client B auto-quickstarts; because
a `!`-prefixed room is already listed, B joins A's room instead of creating one.
A then attacks (space) and both move.
""")
    finally:
        try:
            b.stop()
        except NameError:
            pass
        a.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_combat(args):
    """Two clients, deterministic overlap, then attack until damage/death/respawn.

    The two clients cannot be walked into each other reliably, so the harness
    serves test copies of the stock maps whose 8 spawn slots all point at the
    same tile (see make_test_maps.py). Both players then spawn on the same spot
    and a fist attack lands without any movement.
    """
    d = scenario_dir("combat")
    write_overlay(auto_quickstart=True)
    subprocess.run([sys.executable, os.path.join(HERE, "make_test_maps.py")],
                   check=True, capture_output=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    a = Client("A", d).start()
    b = None
    try:
        assert a.wait_window(), "no Ruffle window A"
        t0 = time.time()
        while time.time() - t0 < 60:
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 8", p["detail"]) for p in pk):
                break
            time.sleep(0.5)
        a.keys(press=["RETURN"])          # dismiss control help

        b = Client("B", d).start()
        assert b.wait_window(), "no Ruffle window B"
        t0 = time.time()
        while time.time() - t0 < 90:
            pk = read_packets(os.path.join(d, "packets.log"))
            spawns = [p for p in pk if p["kind"] == "C->S" and re.match(r"^\d{3} 8", p["detail"])]
            if len(spawns) >= 2:
                break
            time.sleep(0.5)
        b.keys(press=["RETURN"])
        # spawn protection is 133.3 frames (~3.9 s at 34 fps)
        time.sleep(5.0)

        uid_a = uid_for_pid(a.proc.pid, os.path.join(d, "packets.log"))
        uid_b = uid_for_pid(b.proc.pid, os.path.join(d, "packets.log"))
        pa = [p for p in read_packets(os.path.join(d, "packets.log"))
              if p["kind"] == "C->S" and p["detail"].startswith(uid_a + " 8")]
        pb = [p for p in read_packets(os.path.join(d, "packets.log"))
              if p["kind"] == "C->S" and p["detail"].startswith(uid_b + " 8")]

        attacks = 0
        for i in range(20):
            a.keys(down=["SPACE"])
            time.sleep(0.40)
            a.keys(up=["SPACE"])
            attacks += 1
            time.sleep(0.35)
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 7", p["detail"]) for p in pk):
                break
        a.shot(os.path.join(d, "shot_after_attack.png"))
        b.shot(os.path.join(d, "shot_victim.png"))

        # wait for the respawn (dead timer is 150 frames ~ 4.4 s)
        death_t = None
        respawn_t = None
        t0 = time.time()
        while time.time() - t0 < 12:
            pk = read_packets(os.path.join(d, "packets.log"))
            deaths = [p for p in pk if p["kind"] == "C->S" and re.match(r"^\d{3} 7", p["detail"])]
            if deaths:
                death_t = to_seconds(deaths[0]["t"])
                spawns = [p for p in pk if p["kind"] == "C->S"
                          and p["detail"].startswith(uid_b + " 8")]
                for sp in spawns:
                    if to_seconds(sp["t"]) > death_t:
                        respawn_t = to_seconds(sp["t"])
                        break
            if respawn_t:
                break
            time.sleep(0.5)

        pk = read_packets(os.path.join(d, "packets.log"))
        dmg = [p["detail"] for p in pk if p["kind"] == "C->S"
               and re.match(r"^\d{3} 6", p["detail"])]
        deaths = [p["detail"] for p in pk if p["kind"] == "C->S"
                  and re.match(r"^\d{3} 7", p["detail"])]
        res = {
            "scenario": "combat",
            "uid_a": uid_a,
            "uid_b": uid_b,
            "spawn_packets": {"A": [p["detail"] for p in pa][:2],
                              "B": [p["detail"] for p in pb][:3]},
            "attacks_sent": attacks,
            "attack_packets_4": sum(1 for p in pk if p["kind"] == "C->S"
                                    and re.match(r"^\d{3} 4", p["detail"])),
            "damage_packets_6": len(dmg),
            # packet layout: '6' + damage(2) + weapon(1) + angle(3)
            "damage_values": [int(x[5:7]) for x in dmg],
            "total_damage": sum(int(x[5:7]) for x in dmg),
            "damage_sender": sorted({x[:3] for x in dmg}),
            "death_packets_7": len(deaths),
            "death_packet": deaths[0] if deaths else None,
            "respawn_after_death_s": (round(respawn_t - death_t, 2)
                                      if death_t and respawn_t else None),
            "victim_hp_after": 60 - sum(int(x[5:7]) for x in dmg),
        }
        save_result(d, res)
        notes(d, """
# Scenario: combat (2 clients, deterministic overlap)

The harness served test copies of the stock maps with all 8 spawn slots pointing
at one tile (`make_test_maps.py`; only `&sp=` differs). Both clients therefore
spawn on the same spot, so a fist attack lands without any movement input.

Expected from source: the attacker sends `4`; the *victim* runs the hit test,
applies damage locally and emits `6` with the damage value; at 0 HP it emits `7`
and respawns 150 frames (~4.4 s) later.
""")
    finally:
        if b:
            b.stop()
        a.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_round_timer(args):
    """Observe the round clock end-to-end (default 340 s: 300 round + 11 summary + 20 ad)."""
    d = scenario_dir("round-timer")
    write_overlay(auto_quickstart=True, no_perf_watchdog=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    c = Client("A", d).start()
    marks = [0, 5, 15, 30, 120, 240, 290, 296, 300, 303, 308, 315, 322, 330]
    try:
        assert c.wait_window(), "no Ruffle window"
        t0 = time.time()
        while time.time() - t0 < 60:
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 8", p["detail"]) for p in pk):
                break
            time.sleep(1)
        c.keys(press=["RETURN"])          # dismiss control help
        spawn = time.time()
        shots = []
        last_input = time.time()
        for mark in marks:
            while time.time() - spawn < mark:
                # checkNoInput() boots the client after sNoInputBootGameDelay
                # (120 s) with no input; a short direction tap resets it.
                if time.time() - last_input > 30:
                    # alternate direction so `facing` actually changes; move()
                    # only resets noInputTime when the facing string changes
                    c.keys(press=["UP" if int(time.time()) % 2 else "DOWN"])
                    last_input = time.time()
                time.sleep(0.5)
            c.keys(press=["UP" if int(time.time()) % 2 else "DOWN"])
            last_input = time.time()
            time.sleep(0.3)
            name = "shot_%03ds.png" % mark
            if c.shot(os.path.join(d, name)):
                shots.append(name)
        pk = read_packets(os.path.join(d, "packets.log"))
        details = [(p["t"], p["detail"]) for p in pk
                   if p["kind"] == "C->S" and re.search(r" 04", p["detail"])]
        res = {
            "scenario": "round-timer",
            "elapsed_s": round(time.time() - spawn, 1),
            "screenshots": shots,
            "detail_requests": details,
            "detail_request_count": len(details),
        }
        save_result(d, res)
        notes(d, """
# Scenario: round timer (1 client, ~340 s)

Screenshots at 0/5/15/30/120/240/290/296/300/303/308/315/322/330 s after spawn.
The client re-syncs the round clock from the `04` reply (server sends
roundTime+31; client subtracts summary+ad = 31).
""")
    finally:
        c.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


def sc_login_lobby(args):
    """Title screen -> Log In -> credentials -> lobby, using the unmodified ini
    (only sSkipIntro is flipped so the intro does not delay the test)."""
    d = scenario_dir("login-lobby")
    write_overlay(auto_quickstart=False, skip_intro=True)
    h = Harness(os.path.join(d, "packets.log")).start()
    c = Client("A", d).start()
    try:
        assert c.wait_window(), "no Ruffle window"
        time.sleep(8)
        c.shot(os.path.join(d, "shot_title.png"))

        # click the Log In button (coordinates supplied on the command line)
        for (x, y) in args.clicks:
            subprocess.run(PS + [os.path.join(HERE, "click_window.ps1"),
                                 "-ProcId", str(c.proc.pid), "-X", str(x), "-Y", str(y)],
                           capture_output=True)
            time.sleep(1.2)
        c.shot(os.path.join(d, "shot_after_click.png"))

        if args.user:
            c.keys(text=args.user)
            time.sleep(0.3)
            c.keys(press=["TAB"])
            c.keys(text=args.password)
            time.sleep(0.3)
            c.shot(os.path.join(d, "shot_filled.png"))
            c.keys(press=["RETURN"])
            time.sleep(3)

        # wait for the lobby (client sends 01 after authentication)
        t0 = time.time()
        while time.time() - t0 < 20:
            pk = read_packets(os.path.join(d, "packets.log"))
            if any(p["kind"] == "C->S" and re.match(r"^\d{3} 09", p["detail"]) for p in pk):
                break
            time.sleep(0.5)
        time.sleep(3)
        c.shot(os.path.join(d, "shot_lobby.png"))

        pk = read_packets(os.path.join(d, "packets.log"))
        res = {
            "scenario": "login-lobby",
            "packets": [p["detail"] for p in pk if p["kind"] == "C->S"][:14],
            "login_sent": any(re.match(r"^\d{3} 09", p["detail"])
                              for p in pk if p["kind"] == "C->S"),
            "auth_reply": [p["detail"] for p in pk
                           if p["kind"] == "S->C" and " A" in p["detail"]][:2],
            "screenshots": ["shot_title.png", "shot_after_click.png",
                            "shot_filled.png", "shot_lobby.png"],
        }
        save_result(d, res)
        notes(d, """
# Scenario: login -> lobby (1 client, original settings)

Only `sSkipIntro` is flipped (the client's own TEMP DEV switch) so the intro does
not delay the test. The Log In button is clicked at the coordinates given on the
command line, then the form is filled by keyboard.
""")
    finally:
        c.stop()
        h.stop()
    print(json.dumps({"dir": d, "ok": True}))


SCENARIOS = {
    "combat": sc_combat,
    "quickstart": sc_quickstart,
    "movement": sc_movement,
    "collision": sc_collision,
    "two-clients": sc_two_clients,
    "round-timer": sc_round_timer,
    "login-lobby": sc_login_lobby,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--seconds", type=int, default=40)
    ap.add_argument("--clicks", default="", help="x,y;x,y click points in the client area")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    args = ap.parse_args()
    args.clicks = [tuple(int(v) for v in part.split(","))
                   for part in args.clicks.split(";") if "," in part]
    free_ports()
    SCENARIOS[args.scenario](args)


if __name__ == "__main__":
    main()
