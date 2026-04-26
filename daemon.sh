#!/usr/bin/env bash
# dynamic-city daemon — runs continuously, regenerates the wallpaper GIF only
# when the time period or weather conditions change, then applies it via the
# configured setter. Start this from your compositor's exec-once or a systemd
# user service (see install.sh).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR="$SCRIPT_DIR/dynamic-city.py"
STATE_FILE=/tmp/dynamic_city_state

# Read setter + transition from config (fall back to awww/wipe).
_cfg() {
    python3 - "$1" "$2" <<'EOF'
import sys, tomllib
from pathlib import Path
key, default = sys.argv[1], sys.argv[2]
p = Path.home() / '.config' / 'dynamic-city' / 'config.toml'
try:
    cfg = tomllib.load(open(p, 'rb'))
    section, _, field = key.partition('.')
    print(cfg.get(section, {}).get(field, default))
except Exception:
    print(default)
EOF
}

SETTER="$(_cfg wallpaper.setter awww)"
TRANSITION="$(_cfg wallpaper.transition wipe)"

_apply() {
    local gif="$1"
    case "$SETTER" in
        awww) awww clear-cache 2>/dev/null || true
              awww img "$gif" --filter Nearest --transition-type "$TRANSITION" || true ;;
        swww) swww img "$gif" --transition-type "$TRANSITION" --transition-fps 25 || true ;;
        *)    echo "Unknown setter '$SETTER'" >&2 ;;
    esac
}

while true; do
    eval "$(python3 "$GENERATOR" --fetch-weather 2>/dev/null)" || {
        period=night; rain=2; clouds=1; snow=0; vx=1; vy=4; lightning=0; wake=1800
    }

    state="${period}_r${rain}_c${clouds}_s${snow}_x${vx}_y${vy}_l${lightning}_$(date +%Y%m%d)"
    gif="/tmp/dynamic_city_${state}.gif"
    last=$(cat "$STATE_FILE" 2>/dev/null || echo "")

    if [[ "$state" != "$last" || ! -f "$gif" ]]; then
        python3 "$GENERATOR" \
            --period "$period" --rain "$rain" --clouds "$clouds" \
            --snow "$snow" --vx "$vx" --vy "$vy" --lightning "$lightning" \
            --out "$gif"
        echo "$state" > "$STATE_FILE"

        # Export a static frame for the lock screen
        RAIN_CITY_GIF="$gif" python3 -c "
import os; from PIL import Image
img = Image.open(os.environ['RAIN_CITY_GIF'])
img.seek(0)
img.convert('RGB').save('/tmp/dynamic_city_lock.png')
" 2>/dev/null || true

        _apply "$gif"
    else
        _apply "$gif"
    fi

    sleep "$wake"
done
