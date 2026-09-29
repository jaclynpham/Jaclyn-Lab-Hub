#!/usr/bin/env bash
set -euo pipefail
VOICES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/voices"

python3 -m piper \
  --model en_GB-cori-high \
  --data-dir "$VOICES_DIR" \
  --length-scale 1.4 \
  --output-raw \
  -- "Welcome home boss. Let's get it started" \
| aplay -r 22050 -f S16_LE -t raw -

