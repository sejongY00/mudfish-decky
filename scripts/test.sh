#!/usr/bin/env bash
# Run the Python unit tests on the Steam Deck (its python3 matches the target runtime closely).
set -euo pipefail
cd "$(dirname "$0")/.."
DECK="${DECK:-deck@192.168.1.50}"
tar -cf - py_modules tests | ssh "$DECK" '
  rm -rf /tmp/mfd-test && mkdir /tmp/mfd-test && tar -xf - -C /tmp/mfd-test &&
  cd /tmp/mfd-test && PYTHONPATH=py_modules python3 -m unittest discover -s tests -t . -v'
