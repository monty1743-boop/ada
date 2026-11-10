#!/usr/bin/env bash
# Apply the ADA voice patch onto an installed Hermes tree.
# Pin the tree to the commit this patch was made against before running.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
AGENT="${HERMES_AGENT:-$HERMES_HOME/hermes-agent}"
PIN="d923a5eb"

if [[ ! -d "$AGENT/.git" ]]; then
  echo "Hermes checkout not found at $AGENT" >&2
  echo "Install Hermes, then set HERMES_AGENT if it lives somewhere else." >&2
  exit 1
fi

cd "$AGENT"
head="$(git rev-parse --short=10 HEAD)"
if [[ "$head" != "$PIN"* && "$PIN" != "$head"* ]]; then
  echo "This patch matches Hermes commit $PIN. HEAD is $head." >&2
  echo "Check out that commit, or update the patch, before continuing." >&2
  exit 1
fi

if git apply --reverse --check "$ROOT/patches/hermes-watch.patch" >/dev/null 2>&1; then
  echo "patch already applied"
else
  git apply "$ROOT/patches/hermes-watch.patch"
  echo "patch applied"
fi

install -m 644 "$ROOT/assistant/house_hold.py" "$AGENT/gateway/house_hold.py"
echo "installed gateway/house_hold.py"

if [[ -z "${HERMES_PYTHON:-}" ]]; then
  HERMES_PYTHON="$(find "$HERMES_HOME/installs" -path '*/venv/bin/python' -type f 2>/dev/null | head -1 || true)"
fi
if [[ -z "$HERMES_PYTHON" ]]; then
  echo "Set HERMES_PYTHON to the Hermes virtualenv python." >&2
  exit 1
fi

"$HERMES_PYTHON" -m pip install -q 'davey==0.1.7' edge-tts
"$HERMES_PYTHON" - << 'PY'
from pathlib import Path
import faster_whisper, os
audio = Path(faster_whisper.__file__).resolve().parent / "audio.py"
text = audio.read_text()
old = 'with av.open(input_file, metadata_errors="ignore") as container:'
new = 'with av.open(input_file, mode="r") as container:'
if old in text:
    audio.write_text(text.replace(old, new, 1))
    print(f"patched {audio}")
elif new in text:
    print("faster-whisper audio.py already patched")
else:
    raise SystemExit(f"could not find av.open in {audio}")
PY

if [[ -f "$ROOT/personalities/watch-officer.md" && ! -f "$HERMES_HOME/SOUL.md" ]]; then
  install -m 644 "$ROOT/personalities/watch-officer.md" "$HERMES_HOME/SOUL.md"
  echo "installed SOUL.md — edit the commanding officer's name before you start"
fi

echo "Done. Merge config/assistant.yaml.example into $HERMES_HOME/config.yaml,"
echo "put DISCORD_BOT_TOKEN and DISCORD_ALLOWED_USERS in $HERMES_HOME/.env,"
echo "then start: hermes gateway run"
