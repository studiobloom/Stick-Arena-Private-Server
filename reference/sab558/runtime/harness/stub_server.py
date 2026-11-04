#!/usr/bin/env python3
"""
stub_server.py -- repo-local runtime harness for Ballistick 558.

This is NOT a replacement for the Java server and it is NOT shipped code. It is a
test double whose only purpose is to let the *original 558 client* run against a
local endpoint when MySQL / PHP / a JDK are not available.

Every packet format below is transcribed from the Java server in this repository
(`ballistickemu/src/ballistickemu/Tools/StickPacketMaker.java` and the
`Lobby/handlers/*` classes); the line references are given so the transcription
can be audited. If the Java server and this file disagree, the Java server is
right and this file is a bug.

Services
  * HTTP on --http-port (default 80) serving the repository's
    `htdocs/stickarena` read-only, plus the handful of .php endpoints the client
    calls, implemented minimally.
  * TCP on --port (default 1138) speaking the null-terminated text protocol.

Everything is logged to --log (default runtime/evidence/packets.log):
  * every HTTP request (method, path, bytes, status)
  * every socket connect/disconnect
  * every client->server and server->client message, escaped

Usage
  python runtime/harness/stub_server.py [--port 1138] [--http-port 80]
                                        [--log PATH] [--quiet]

Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.dirname(HERE)                     # reference/sab558/runtime
REF = os.path.dirname(RUNTIME)                      # reference/sab558
REPO = os.path.dirname(os.path.dirname(REF))        # repo root
WEBROOT = os.path.join(REPO, "htdocs", "stickarena")
# Overlay served *instead of* WEBROOT for the same relative path. Used only for
# test-time configuration (e.g. a settings558b.ini with sAutoQuickStart=1); the
# repository's original files are never modified.
OVERLAY = os.path.join(RUNTIME, "http")

LOCK = threading.RLock()
LOG_LOCK = threading.Lock()
LOG_PATH = None


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def esc(s: str) -> str:
    """Make a wire string readable in a log: show NUL and CR/LF explicitly."""
    return (s.replace("\0", "<NUL>").replace("\r", "<CR>").replace("\n", "<LF>"))


def log(kind: str, detail: str) -> None:
    line = "%s %-6s %s" % (
        datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3], kind, detail)
    with LOG_LOCK:
        print(line, flush=True)
        if LOG_PATH:
            with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")


# --------------------------------------------------------------------------
# packet builders (transcribed from StickPacketMaker.java)
# --------------------------------------------------------------------------
def pad_left(s, ch, n):
    s = str(s)
    return ch * max(0, n - len(s)) + s


def server_hello():
    return "08"                                          # :39-43


def login_failed():
    return "09"                                          # :140-145


def error_packet(code):
    return "09" + str(code)                              # :147-153


def login_success(uid, name, colour, stats):
    """A + uid + name(20,'#') + colour(9) + colour(9) + k;d;w;l;r;pass;exp;tkt;cash;lvl
    StickPacketMaker.java:155-186; client parse at frame_1/DoAction.as:5593-5618."""
    k, d, w, l, r, pas, exp, tkt, cash, lvl = stats
    return ("A" + uid + pad_left(name, "#", 20) + colour + colour +
            ";".join(str(x) for x in (k, d, w, l, r, pas, exp, tkt, cash, lvl)))


def client_info(uid, name, colour, kills, deaths, wins, losses, rounds, pas, level):
    """StickPacketMaker.java:187-212"""
    return ("U" + uid + pad_left(name, "#", 20) + colour +
            ";".join(str(x) for x in (kills, deaths, wins, losses, rounds, pas, level)))


def new_player_uid(uid):
    return "C" + uid                                     # :45-51


def disconnected(uid):
    return "D" + uid                                     # :86-92


def room_list(rooms, client_uid):
    """StickPacketMaker.getRoomList -> '01' + GetRoomPacketInfo.
    GetRoomPacketInfo (StickRoomRegistry.java:81-106) = '_0;' + name + passFlag + ';'"""
    body = "_0;"
    for r in rooms:
        body += r.name + ("1" if r.needs_pass else "0") + ";"
    return "01" + body


def round_detail(map_id, cycle_mode, players, round_time):
    """StickPacketMaker.java:94-104 (client subtracts summary+ad = 31, :5205)"""
    return "04" + str(map_id) + str(cycle_mode) + str(players) + str(round_time + 31)


def room_variable_map(map_id):
    return "06mp=" + str(map_id)                        # :106-112


def room_variable_creator(name):
    return "06rc=" + name                               # :387-393


def user_data_game(uid, game_wins, game_kills, game_deaths, name, spinner_id,
                   colour1, colour2, kills, pet_id, pet_c1, pet_c2):
    """StickPacketMaker.java:366-386. Note: no separators, fixed widths."""
    return ("U" + uid + str(game_wins) + pad_left(game_kills, "0", 2) +
            pad_left(game_deaths, "0", 2) + pad_left(name, "#", 20) +
            spinner_id + colour1 + colour2 + pet_id + pet_c1 + pet_c2 + str(kills))


def user_list_game(members, joiner_uid):
    """StickPacketMaker.getUserListGame: C+uid then U+uid for every other member."""
    out = ""
    for c in members:
        if c.uid == joiner_uid:
            continue
        out += new_player_uid(c.uid) + user_data_game(
            c.uid, 0, 0, 0, c.name, "00", c.colour, c.colour, 0, "00", "000000000", "000000000")
    return out


def creds_ticket(amount):
    return "0a" + str(amount)                            # :445-451


def inventory_packet(formatted):
    return "0c" + formatted                              # :404-411


def announce(message):
    return "0j" + message                                # :413-419


def mod_warn(message):
    return "0g" + message                                # :421-426


def callback(message):
    return "0h" + message                                # :428-436


def kicked():
    return "094"                                         # :473-478


def broadcast(packet, from_uid):
    """M + sender + payload (StickPacketMaker.java:122-128)"""
    return "M" + from_uid + packet


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------
class Client:
    _next_uid = 1

    def __init__(self, conn, addr):
        with LOCK:
            self.uid = "%03d" % Client._next_uid
            Client._next_uid += 1
        self.conn = conn
        self.addr = addr
        self.name = None
        self.colour = "255255255"
        self.room = None
        self.lobby = True
        self.in_game = False
        self.spinner_id = "00"
        self.pet_id = "00"
        self.stats = (0, 0, 0, 0, 0, 0, 0, 0, 100000, 0)
        self.alive = True

    def send(self, text):
        if not self.alive:
            return
        try:
            self.conn.sendall((text + "\0").encode("utf-8"))
            log("S->C", "%s %s" % (self.uid, esc(text)))
        except OSError:
            self.alive = False

    def send_raw(self, data: bytes):
        try:
            self.conn.sendall(data)
            log("S->C", "%s %s" % (self.uid, esc(data.decode("utf-8", "replace"))))
        except OSError:
            self.alive = False


class Room:
    def __init__(self, name, map_id, cycle_mode, needs_pass, creator):
        self.name = name
        self.map_id = map_id
        self.cycle_mode = cycle_mode
        self.needs_pass = needs_pass
        self.creator = creator
        self.cycle = ""
        self.created = time.time()
        self.members = []

    @property
    def round_time(self):
        """Mirror StickRoom's 1 s timer: 300 down to -30, then reset (Java: :259-265).

        The client re-syncs from this value every ~16 s (frame_1:5205), so a
        constant value would keep the round alive forever.
        """
        elapsed = int(time.time() - self.created)
        rt = 300 - elapsed
        while rt <= -30:
            rt += 330
        return rt

    def broadcast(self, text, except_uid=None):
        for c in list(self.members):
            if except_uid and c.uid == except_uid:
                continue
            c.send(text)


CLIENTS = []
ROOMS = []


def find_client(uid):
    for c in CLIENTS:
        if c.uid == uid:
            return c
    return None


def find_room(name):
    for r in ROOMS:
        if r.name == name:
            return r
    return None


# --------------------------------------------------------------------------
# protocol
# --------------------------------------------------------------------------
def handle_message(c: Client, msg: str) -> None:
    msg = msg.rstrip("\0")
    if not msg:
        return
    op = msg[:2]
    log("C->S", "%s %s" % (c.uid, esc(msg)))

    # --- pre-login -------------------------------------------------------
    if op == "08":                                   # CheckCapacityHandler
        c.send(server_hello())
        return

    if op == "09":                                   # LoginHandler
        body = msg[2:]
        parts = body.split(";")
        name = parts[0][:20] if parts else "unknown"
        c.name = name
        c.lobby = True
        if c not in CLIENTS:
            CLIENTS.append(c)
        log("EVENT", "login uid=%s name=%s (password not validated by the stub)" % (c.uid, name))
        c.send(login_success(c.uid, name, c.colour, c.stats))
        return

    if op == "01":                                   # RoomRequestHandler
        c.send(room_list(ROOMS, c.uid))
        return

    if op == "02":                                   # CreateRoomHandler
        # 02 <map> <cycle> <private> <labpass> <name>[;<vip>;...]
        data = msg
        if ";" in data:
            data = data.split(";")[0]
        map_id = data[2:3]
        cycle_mode = data[3:4]
        private = data[4:5] == "1"
        needs_pass = data[5:6] == "1"
        name = data[6:].rstrip("\0")
        if find_room(name):
            c.send(error_packet("42"))
            return
        r = Room(name, map_id, int(cycle_mode or 0), needs_pass, c.name)
        with LOCK:
            ROOMS.append(r)
        r.members.append(c)
        c.room = r
        c.lobby = False
        c.in_game = True
        log("EVENT", "room created %r map=%s cycle=%s private=%s" % (name, map_id, cycle_mode, private))
        r.broadcast(new_player_uid(c.uid))
        r.broadcast(user_data_game(c.uid, 0, 0, 0, c.name, c.spinner_id,
                                   c.colour, c.colour, 0, c.pet_id,
                                   "000000000", "000000000"))
        return

    if op == "03":                                   # NewClientHandler (join)
        name = msg[2:].rstrip("\0")
        if name == "_":                              # back to lobby
            if c.room:
                c.room.members.remove(c)
                c.room.broadcast(disconnected(c.uid))
                c.room = None
            c.lobby = True
            c.in_game = False
            c.send(room_list(ROOMS, c.uid))
            return
        r = find_room(name)
        if not r:
            log("EVENT", "join failed, no room %r" % name)
            c.send(error_packet("4"))
            return
        r.members.append(c)
        c.room = r
        c.lobby = False
        c.in_game = True
        log("EVENT", "join uid=%s room=%r members=%d" % (c.uid, name, len(r.members)))
        r.broadcast(new_player_uid(c.uid))
        r.broadcast(user_data_game(c.uid, 0, 0, 0, c.name, c.spinner_id,
                                   c.colour, c.colour, 0, c.pet_id,
                                   "000000000", "000000000"))
        others = user_list_game(r.members, c.uid)
        if others:
            c.send(others)
        return

    if op == "04":                                   # RoomDetailRequestHandler
        name = msg[2:].rstrip("\0")
        r = find_room(name)
        if r:
            c.send(round_detail(r.map_id, r.cycle_mode, len(r.members), r.round_time))
        return

    if op == "05":                                   # SetMapCycleListHandler
        body = msg[2:].rstrip("\0")
        if body.startswith("mp="):
            cycle = body[3:]
            if c.room:
                c.room.cycle = cycle
            log("EVENT", "map cycle set to %r by %s" % (cycle, c.uid))
            if c.room:
                c.room.broadcast(room_variable_map(cycle))
        return

    if op == "06":                                   # MapCycleRequestHandler
        body = msg[2:].rstrip("\0")
        target, _, var = body.partition(";")
        r = find_room(target)
        if r:
            if var == "mp":
                c.send(room_variable_map(r.cycle or r.map_id))
            elif var == "rc":
                c.send(room_variable_creator(r.creator))
        return

    if op == "0a":                                   # GiveTicketHandler
        c.send(creds_ticket(0))
        return

    if op == "0c":                                   # InventoryRequestHandler
        c.send(inventory_packet(""))
        return

    if op in ("0b", "0d", "0g", "0f", "0e", "0l", "0m", "0j", "07", "0h", "0i", "0k"):
        log("EVENT", "stub: opcode %r acknowledged, no game effect" % op)
        return

    if op == "9":                                    # GeneralChatHandler
        text = msg[1:]
        if c.room:
            c.room.broadcast(broadcast("9" + text, c.uid))
        else:
            for other in CLIENTS:
                if other.lobby:
                    other.send(broadcast("9" + text, c.uid))
        return

    if op == "00":                                   # GenericSendDataHandler
        target = msg[2:5]
        payload = msg[5:]
        t = find_client(target)
        if t:
            t.send(broadcast(payload, c.uid))
        return

    if op == "K":                                    # VoteKickHandler
        target = msg[1:4]
        if c.room:
            c.room.broadcast(broadcast("K" + target, c.uid))
        return

    # --- in-game relay: 1/2/4/5/6/7/8 --------------------------------
    # The Java server broadcasts to *every* room member, including the sender
    # (StickRoom.BroadcastToRoom). The echo is not cosmetic: the client boots to
    # the title screen if it receives nothing for sServerTimeout (10 s), so a
    # lone player relies on hearing its own packets back.
    if msg[0] in "1245678" and c.room:
        c.room.broadcast(broadcast(msg, c.uid))
        return

    log("EVENT", "unhandled message from %s: %r" % (c.uid, msg))


class ProtoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        conn.settimeout(None)
        c = Client(conn, self.client_address)
        log("EVENT", "connect %s (assigned uid %s)" % (self.client_address, c.uid))
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                # Flash sends the policy request without a NUL terminator.
                if buf.startswith(b"<policy-file-request/>"):
                    log("C->S", "%s <policy-file-request/>" % c.uid)
                    policy = ('<?xml version="1.0"?><!DOCTYPE cross-domain-policy SYSTEM '
                              '"http://www.adobe.com/xml/dtds/cross-domain-policy.dtd">'
                              '<cross-domain-policy><allow-access-from domain="*" to-ports="*"/>'
                              '</cross-domain-policy>\0').encode()
                    c.send_raw(policy)
                    buf = buf[len(b"<policy-file-request/>"):]
                    continue
                while b"\0" in buf:
                    raw, buf = buf.split(b"\0", 1)
                    if not raw:
                        continue
                    try:
                        handle_message(c, raw.decode("utf-8", "replace"))
                    except Exception as e:           # never kill the harness on one packet
                        log("ERROR", "handling %r: %s" % (raw[:80], e))
        except OSError:
            pass
        finally:
            c.alive = False
            with LOCK:
                if c in CLIENTS:
                    CLIENTS.remove(c)
                if c.room and c in c.room.members:
                    c.room.members.remove(c)
                    c.room.broadcast(disconnected(c.uid))
                if c.room and not c.room.members:
                    if c.room in ROOMS:
                        ROOMS.remove(c.room)
            log("EVENT", "disconnect %s" % c.uid)
            try:
                conn.close()
            except OSError:
                pass


# --------------------------------------------------------------------------
# HTTP (static + the .php endpoints the client calls)
# --------------------------------------------------------------------------
class HttpHandler(BaseHTTPRequestHandler):
    server_version = "sab558-harness"

    def log_message(self, fmt, *args):
        pass

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, body: bytes, ctype="text/plain; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        query = parse_qs(parsed.query)

        if path.endswith(".php"):
            self._php(path, body, query)
            return

        rel = path.lstrip("/")
        if not rel:
            rel = "index.php"
        overlay_path = os.path.normpath(os.path.join(OVERLAY, rel))
        if overlay_path.startswith(OVERLAY) and os.path.isfile(overlay_path):
            with open(overlay_path, "rb") as f:
                data = f.read()
            log("HTTP", "%s %s -> 200 (%d bytes, overlay)" % (method, path, len(data)))
            self._send(data, "text/plain; charset=utf-8")
            return
        fs_path = os.path.normpath(os.path.join(WEBROOT, rel))
        if not fs_path.startswith(WEBROOT) or not os.path.isfile(fs_path):
            log("HTTP", "%s %s -> 404" % (method, path))
            self._send(b"not found", code=404)
            return
        with open(fs_path, "rb") as f:
            data = f.read()
        ctype = "application/octet-stream"
        if fs_path.endswith(".ini") or fs_path.endswith(".dat") or fs_path.endswith(".csv"):
            ctype = "text/plain; charset=utf-8"
        log("HTTP", "%s %s -> 200 (%d bytes)" % (method, path, len(data)))
        self._send(data, ctype)

    def _php(self, path, body, query):
        form = {}
        if body:
            for part in body.decode("utf-8", "replace").split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    form[k] = v
        action = form.get("action") or (query.get("action") or [None])[0]
        method = (query.get("method") or [None])[0] or form.get("method")

        if path.endswith("version_check.php"):
            ver = form.get("ver") or (query.get("ver") or [""])[0]
            log("HTTP", "POST /version_check.php ver=%s -> success" % ver)
            self._send(b"result=success")
            return

        if path.endswith("stick_arena.php"):
            log("HTTP", "POST /stick_arena.php action=%s -> success" % action)
            if action == "authenticate":
                self._send(b"result=success&usercol=255255255")
            elif action in ("create", "start_round", "round_stats", "player_stats"):
                self._send(b"result=success")
            else:
                self._send(b"result=error")
            return

        if path.endswith("api.php"):
            log("HTTP", "POST /api.php method=%s -> empty map list" % method)
            self._send(b'<rsp stat="ok">\n\t<maps>\n\t</maps>\n</rsp>')
            return

        log("HTTP", "POST %s -> stub success" % path)
        self._send(b"result=success")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class ThreadingHTTPServer6(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ThreadingTCPServer6(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1138)
    ap.add_argument("--http-port", type=int, default=80)
    ap.add_argument("--log", default=os.path.join(RUNTIME, "evidence", "packets.log"))
    args = ap.parse_args()

    global LOG_PATH
    LOG_PATH = args.log
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    open(LOG_PATH, "w", encoding="utf-8").close()

    log("EVENT", "webroot=%s" % WEBROOT)
    log("EVENT", "http on 127.0.0.1:%d, socket on 127.0.0.1:%d" % (args.http_port, args.port))

    httpd = ThreadingHTTPServer6(("127.0.0.1", args.http_port), HttpHandler)
    tcpd = ThreadingTCPServer6(("127.0.0.1", args.port), ProtoHandler)

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        tcpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tcpd.shutdown()
        httpd.shutdown()
        log("EVENT", "harness stopped")


if __name__ == "__main__":
    main()
