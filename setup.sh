#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Groovebox Pi — setup script
#
# Run once after cloning:   bash setup.sh
# Run on Raspberry Pi:      bash setup.sh --pi
#
# --pi flag applies Pi-specific steps:
#   • Enables SPI + I2S in /boot/firmware/config.txt (or /boot/config.txt)
#   • Installs Pirate Audio / ST7789 Python libraries
#   • Installs gpiozero for hardware buttons
#   • Disables the conflicting onboard audio driver
#   • Creates a systemd service so the app auto-starts on boot
# ─────────────────────────────────────────────────────────────────────────────
set -e

PI_MODE=0
for arg in "$@"; do
  [[ "$arg" == "--pi" ]] && PI_MODE=1
done

# ── System packages ───────────────────────────────────────────────────────────
if command -v apt-get &>/dev/null; then
    echo ">>> Installing system packages…"
    sudo apt-get update -qq
    sudo apt-get install -y \
        libportaudio2 portaudio19-dev \
        python3-tk python3-venv python3-pip \
        --quiet

    if [[ $PI_MODE -eq 1 ]]; then
        sudo apt-get install -y \
            python3-gpiozero python3-rpi.gpio \
            python3-spidev python3-pil \
            --quiet
    fi

elif command -v brew &>/dev/null; then
    echo ">>> Installing Homebrew packages…"
    brew install portaudio
else
    echo "WARNING: could not detect package manager."
    echo "  macOS: install Homebrew (brew.sh) then re-run."
    echo "  Linux: sudo apt-get install libportaudio2 portaudio19-dev python3-tk"
fi

# ── Python virtualenv ─────────────────────────────────────────────────────────
echo ">>> Creating virtualenv…"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

if [[ $PI_MODE -eq 1 ]]; then
    echo ">>> Installing Pi-specific Python packages…"
    .venv/bin/pip install ST7789 --quiet       # Pimoroni ST7789 display driver
    .venv/bin/pip install gpiozero RPi.GPIO --quiet
fi

# ── Data directories ──────────────────────────────────────────────────────────
mkdir -p samples kits sequences

# ── Pi hardware configuration ─────────────────────────────────────────────────
if [[ $PI_MODE -eq 1 ]]; then
    echo ""
    echo ">>> Configuring Raspberry Pi hardware…"

    # Find the right config file (Pi OS Bookworm moved it)
    if [[ -f /boot/firmware/config.txt ]]; then
        CONFIG=/boot/firmware/config.txt
    else
        CONFIG=/boot/config.txt
    fi

    echo "    Config file: $CONFIG"

    apply_config() {
        local KEY="$1" VAL="$2"
        if grep -q "^${KEY}" "$CONFIG" 2>/dev/null; then
            sudo sed -i "s|^${KEY}.*|${VAL}|" "$CONFIG"
            echo "    Updated: $VAL"
        else
            echo "$VAL" | sudo tee -a "$CONFIG" > /dev/null
            echo "    Added:   $VAL"
        fi
    }

    # Enable SPI (required by ST7789 display)
    apply_config "dtparam=spi" "dtparam=spi=on"

    # Enable I2S (required by Pirate Audio MAX98357A amp)
    apply_config "dtparam=i2s" "dtparam=i2s=on"

    # Load HifiBerry DAC overlay (compatible with Pirate Audio)
    if ! grep -q "dtoverlay=hifiberry-dac" "$CONFIG" 2>/dev/null; then
        echo "dtoverlay=hifiberry-dac" | sudo tee -a "$CONFIG" > /dev/null
        echo "    Added:   dtoverlay=hifiberry-dac"
    fi

    # Disable the conflicting onboard bcm2835 audio (it blocks I2S)
    apply_config "dtparam=audio" "dtparam=audio=off"

    # ── ALSA config for Pirate Audio ─────────────────────────────────────────
    ALSA_CONF=/etc/asound.conf
    echo ">>> Writing ALSA config → $ALSA_CONF"
    sudo tee "$ALSA_CONF" > /dev/null <<'ASOUND'
pcm.!default {
    type hw
    card 0
}
ctl.!default {
    type hw
    card 0
}
ASOUND

    # ── Systemd service ───────────────────────────────────────────────────────
    INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
    SERVICE=/etc/systemd/system/groovebox.service
    USER_NAME="$(whoami)"

    echo ">>> Creating systemd service → $SERVICE"
    sudo tee "$SERVICE" > /dev/null <<SERVICE
[Unit]
Description=Groovebox Pi
After=sound.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/main.py --headless
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE

    sudo systemctl daemon-reload
    sudo systemctl enable groovebox.service
    echo "    Service enabled. It will start automatically on next boot."
    echo "    To start now:  sudo systemctl start groovebox"
    echo "    To check logs: sudo journalctl -u groovebox -f"

    echo ""
    echo ">>> A reboot is required to activate I2S and SPI."
    echo "    sudo reboot"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Setup complete."
echo ""
echo "  Development / HDMI debug:"
echo "    .venv/bin/python main.py"
echo ""
echo "  Headless (Pi LCD only):"
echo "    .venv/bin/python main.py --headless"
echo ""
echo "  List MIDI devices:"
echo "    .venv/bin/python list_midi.py"
echo ""
echo "  Test audio latency:"
echo "    .venv/bin/python test_audio_latency.py"
