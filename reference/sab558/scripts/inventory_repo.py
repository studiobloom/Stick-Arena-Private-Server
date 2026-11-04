#!/usr/bin/env python3
"""
inventory_repo.py -- classify every tracked file in this repository by whether it
belongs to the Ballistick 558 target, to another client version, or to shared
server/web infrastructure.

Scope rule (from AGENTS.md): the only client target is sab558. Files for 563,
588, 593, 598/Dimensions are recorded so they are *excluded*, never used as
reference material.

Outputs
  analysis/repo_inventory.json   machine-readable classification + hashes
  analysis/repo_inventory.md     human table
  analysis/settings558b.json     parsed settings558b.ini
  analysis/upgradevalues558.json parsed upgradevalues558.ini
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict

SKIP_DIRS = {".git", "node_modules", "extracted", "logs"}

# explicit, evidence-based classification rules (first match wins)
RULES = [
    # (regex on repo-relative posix path, scope, role, note)
    (r"^htdocs/stickarena/sab558\.swf$", "target",
     "client", "Ballistick 558 Flash client (the extraction target)"),
    (r"^htdocs/stickarena/settings558b\.ini$", "target",
     "client-config", "558 client settings: server list, controls, map cycle, gameplay values"),
    (r"^htdocs/stickarena/upgradevalues558\.ini$", "target",
     "client-config", "558 shop/upgrade price and item table"),
    (r"^htdocs/stickarena/maps/558/", "target",
     "map", "558 map data served to the client"),
    (r"^htdocs/stickarena/maps/5(63|93)/", "other-version",
     "map", "map set for another client build - NOT a 558 reference"),
    (r"^htdocs/stickarena/sab588\.swf$", "other-version",
     "client", "Ballistick 588 client - out of scope"),
    (r"^htdocs/stickarena/dimensions\.swf$", "other-version",
     "client", "Stick Arena Dimensions client - out of scope"),
    (r"^htdocs/stickarena/settings588b\.ini$", "other-version",
     "client-config", "588 settings - out of scope"),
    (r"^htdocs/stickarena/settings598b\.ini$", "other-version",
     "client-config", "598/Dimensions settings - out of scope"),
    (r"^htdocs/stickarena/upgradevalues588\.ini$", "other-version",
     "client-config", "588 upgrade values - out of scope"),
    (r"^htdocs/stickarena/upgradevalues598\.ini$", "other-version",
     "client-config", "598/Dimensions upgrade values - out of scope"),
    (r"^htdocs/stickarena/ballistick/ingame/.*\.swf$", "shared",
     "client-module", "in-game shop/pass SWF loaded by the client (version-agnostic UI module)"),
    (r"^htdocs/stickarena/ballistick/(eula|faq)\.dat$", "shared",
     "client-data", "legal/FAQ text loaded by the client"),
    (r"^htdocs/stickarena/com/languagefilter\.ini$", "shared",
     "client-data", "profanity filter list used by client and server"),
    (r"^htdocs/stickarena/api\.php$", "shared",
     "web-backend", "map storage/retrieval + xgen map import API"),
    (r"^htdocs/stickarena/stick_arena\.php$", "shared",
     "web-backend", "account, stats, inventory, highscore HTTP endpoint used by the client"),
    (r"^htdocs/stickarena/version_check\.php$", "shared",
     "web-backend", "client version gate (accepts 558/588/598)"),
    (r"^htdocs/stickarena/(index|lostaccount|recover)\.php$", "shared",
     "web-frontend", "web front end around the SWF"),
    (r"^htdocs/stickarena/class\.rc4crypt\.php$", "shared",
     "web-backend", "RC4 helper used by the PHP endpoints"),
    (r"^htdocs/stickarena/crossdomain\.xml$", "shared",
     "web-config", "Flash socket policy for the game server"),
    (r"^htdocs/stickarena/(mapEditorTiles\.csv)$", "shared",
     "web-data", "map editor tile reference"),
    (r"^htdocs/stickarena/images/", "shared",
     "web-asset", "rank/box images used by the PHP front end"),
    (r"^htdocs/stickarena/styles/", "shared",
     "web-asset", "CSS for the PHP front end"),
    (r"^htdocs/stickarena/stickarena/", "shared",
     "web-backend", "highscore / email verification pages"),
    (r"^htdocs/swf_filler_pages/", "shared",
     "web-frontend", "placeholder pages for links embedded in the SWF"),
    (r"^Import database/.*\.sql$", "shared",
     "database", "MySQL schema and seed data for the server"),
    (r"^ballistickemu/.*\.java$", "shared",
     "server", "BallistickEMU game server (Java/MINA, version-agnostic)"),
    (r"^ballistickemu/(pom\.xml|config\.properties|log4j2\.xml|run\.bat|\.gitignore)$", "shared",
     "server-config", "server build/run configuration"),
    (r"^README\.md$", "shared", "doc", "project README"),
    (r"^\.gitignore$", "shared", "repo-config", "git ignore rules for derived 558 output"),
    (r"^htdocs/stickarena/ballistick/recover\.php$", "shared",
     "web-frontend", "account recovery page linked from the client"),
    (r"^\.gitattributes$", "shared", "repo-config", "git attributes"),
    (r"^AGENTS\.md$", "shared", "doc", "workspace rules for agents"),
    (r"^reference/sab558/", "generated", "workspace", "this workspace (tools, manifests, docs)"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(rel):
    for pat, scope, role, note in RULES:
        if re.search(pat, rel):
            return scope, role, note
    return "unclassified", "unknown", "no rule matched - review manually"


def parse_amp_ini(path):
    """Parse the '&key=value&' ini dialect used by the Stick Arena client.

    Section headers are '/// NAME ///' lines. Values may contain '&' only as a
    separator, so the file is split on '&' and each token is key=value.
    """
    sections = OrderedDict()
    current = "_root"
    sections[current] = OrderedDict()
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^///\s*(.*?)\s*///$", line)
            if m:
                current = m.group(1)
                sections.setdefault(current, OrderedDict())
                continue
            if line.startswith("//"):
                continue
            for token in line.split("&"):
                token = token.strip()
                if not token or "=" not in token:
                    continue
                k, v = token.split("=", 1)
                sections[current][k.strip()] = v.strip()
    return sections


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = os.path.abspath(argv[1])
    ana = os.path.join(root, "reference", "sab558", "analysis")
    os.makedirs(ana, exist_ok=True)

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not d.startswith(".git"))
        for fn in sorted(filenames):
            abspath = os.path.join(dirpath, fn)
            rel = os.path.relpath(abspath, root).replace("\\", "/")
            scope, role, note = classify(rel)
            files.append(OrderedDict([
                ("path", rel),
                ("scope", scope),
                ("role", role),
                ("note", note),
                ("bytes", os.path.getsize(abspath)),
                ("sha256", sha256(abspath)),
            ]))

    counts = Counter(f["scope"] for f in files)
    roles = Counter(f["role"] for f in files)
    payload = OrderedDict()
    payload["repo_root"] = root.replace("\\", "/")
    payload["scope_legend"] = {
        "target": "required for the Ballistick 558 workspace",
        "shared": "used by 558 but not version-specific",
        "other-version": "belongs to another client build; excluded from reference use",
        "generated": "produced by this workspace's pipeline",
        "unclassified": "needs manual review",
    }
    payload["counts_by_scope"] = dict(sorted(counts.items()))
    payload["counts_by_role"] = dict(sorted(roles.items()))
    payload["files"] = files
    with open(os.path.join(ana, "repo_inventory.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # ---- markdown summary
    lines = ["# Repository inventory (558 scope)", "",
             "Generated by `reference/sab558/scripts/inventory_repo.py`.", "",
             "| scope | files |", "| --- | --- |"]
    for k, v in payload["counts_by_scope"].items():
        lines.append("| %s | %d |" % (k, v))
    lines += ["", "## Files that define the 558 target", "",
              "| path | role | note |", "| --- | --- | --- |"]
    for f in files:
        if f["scope"] == "target":
            lines.append("| `%s` | %s | %s |" % (f["path"], f["role"], f["note"]))
    lines += ["", "## Excluded (other client versions)", "",
              "| path | role | note |", "| --- | --- | --- |"]
    for f in files:
        if f["scope"] == "other-version":
            lines.append("| `%s` | %s | %s |" % (f["path"], f["role"], f["note"]))
    lines += ["", "## Shared server / web / database files", "",
              "| path | role |", "| --- | --- |"]
    for f in files:
        if f["scope"] == "shared":
            lines.append("| `%s` | %s |" % (f["path"], f["role"]))
    lines.append("")
    with open(os.path.join(ana, "repo_inventory.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    # ---- parsed 558 ini files
    for ini, outname in (("settings558b.ini", "settings558b.json"),
                         ("upgradevalues558.ini", "upgradevalues558.json")):
        src = os.path.join(root, "htdocs", "stickarena", ini)
        if not os.path.exists(src):
            continue
        parsed = parse_amp_ini(src)
        with open(os.path.join(ana, outname), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"source": "htdocs/stickarena/" + ini,
                       "sections": parsed}, f, indent=2, ensure_ascii=False)
            f.write("\n")

    print("inventoried %d files: %s" % (len(files), dict(counts)))
    print("wrote analysis/repo_inventory.{json,md}, settings558b.json, upgradevalues558.json")
    unclassified = [f["path"] for f in files if f["scope"] == "unclassified"]
    if unclassified:
        print("unclassified (%d):" % len(unclassified))
        for p in unclassified[:40]:
            print("  " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
