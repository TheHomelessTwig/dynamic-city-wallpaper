#!/usr/bin/env bash
# dynamic-city installer
# Installs the daemon as a systemd user service, or prints the exec-once line
# for Hyprland. Run with no arguments for interactive mode.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="dynamic-city"
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"

_check_deps() {
    local missing=()
    command -v python3 &>/dev/null || missing+=("python3")
    python3 -c "from PIL import Image" 2>/dev/null || missing+=("python3-pillow (pip install Pillow)")
    python3 -c "import tomllib" 2>/dev/null || missing+=("python3 >= 3.11")
    if ! command -v awww &>/dev/null && ! command -v swww &>/dev/null; then
        missing+=("awww or swww (animated GIF wallpaper setter)")
    fi
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "Missing dependencies:"
        for d in "${missing[@]}"; do echo "  - $d"; done
        echo ""
    fi
}

_install_service() {
    mkdir -p "$(dirname "$SERVICE_FILE")"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=dynamic-city animated wallpaper daemon
After=graphical-session.target

[Service]
ExecStart=${SCRIPT_DIR}/daemon.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    echo "Service installed and started: $SERVICE_NAME"
    echo "  Stop:    systemctl --user stop $SERVICE_NAME"
    echo "  Logs:    journalctl --user -u $SERVICE_NAME -f"
}

_uninstall_service() {
    systemctl --user disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    echo "Service removed."
}

_hyprland_line() {
    echo ""
    echo "Add this line to your hyprland.conf exec-once section:"
    echo "  exec-once = bash -c 'sleep 0.5 && ${SCRIPT_DIR}/daemon.sh'"
    echo ""
}

echo "=== dynamic-city installer ==="
echo ""
_check_deps

if [[ "${1:-}" == "--uninstall" ]]; then
    _uninstall_service
    exit 0
fi

if [[ "${1:-}" == "--hyprland" ]]; then
    _hyprland_line
    exit 0
fi

echo "Where do you want to run dynamic-city?"
echo "  1) systemd user service (recommended for most Wayland compositors)"
echo "  2) Hyprland exec-once  (print the line to add to hyprland.conf)"
echo "  3) Exit"
read -rp "Choice [1-3]: " choice

case "$choice" in
    1) _install_service ;;
    2) _hyprland_line ;;
    *) echo "Exiting."; exit 0 ;;
esac

echo ""
echo "Run setup first if you haven't already:"
echo "  python3 ${SCRIPT_DIR}/dynamic-city.py --init"
