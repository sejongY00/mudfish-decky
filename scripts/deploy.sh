#!/usr/bin/env bash
# Build the frontend and install the plugin on the Steam Deck, then restart Decky.
# Needs passwordless sudo for the deck user (development only).
set -euo pipefail
cd "$(dirname "$0")/.."
DECK="${DECK:-deck@192.168.1.50}"
pnpm build
tar --exclude='__pycache__' -cf - dist main.py plugin.json package.json py_modules | ssh "$DECK" '
  D=/home/deck/homebrew/plugins/mudfish-decky
  sudo rm -rf "$D" && sudo mkdir -p "$D" && sudo tar --no-same-owner -xf - -C "$D" &&
  sudo systemctl restart plugin_loader'
echo "deployed to $DECK"
