#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# fetch_runtime.sh -- install the Flash runtime used for runtime verification.
#
# Downloads a pinned Ruffle release into runtime/tools/ and verifies its
# SHA-256. Nothing is installed system-wide: no PATH change, no registry, no
# Program Files write. Re-running is a no-op once the binary matches.
#
# Ruffle is a Flash Player *emulator*. It is used because no Adobe Flash Player
# runtime exists on this machine; see docs/systems/09-runtime-evidence.md.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$SCRIPT_DIR"
DEST="$TOOLS/ruffle"
VERSION="0.7.1"
URL="https://github.com/ruffle-rs/ruffle/releases/download/v${VERSION}/ruffle-${VERSION}-windows-x86_64.zip"
SHA256="a5f6df9881771226e330e08a1fa7666f4caff50ddf9f2f993cdd95293edca627"

if [[ -x "$DEST/ruffle.exe" ]]; then
  echo "ruffle already present: $DEST/ruffle.exe"
  "$DEST/ruffle.exe" --version || true
  exit 0
fi

mkdir -p "$TOOLS"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "downloading $URL"
curl -sSL -o "$TMP/ruffle.zip" "$URL"

ACTUAL="$(python - "$TMP/ruffle.zip" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"
if [[ "$ACTUAL" != "$SHA256" ]]; then
  echo "checksum mismatch: expected $SHA256 got $ACTUAL" >&2
  exit 1
fi

mkdir -p "$DEST"
unzip -q -o "$TMP/ruffle.zip" -d "$DEST"
printf '%s  ruffle-%s-windows-x86_64.zip\n' "$SHA256" "$VERSION" > "$TOOLS/CHECKSUMS.txt"
echo "installed to $DEST"
"$DEST/ruffle.exe" --version || true
