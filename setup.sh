#!/usr/bin/env bash
set -e

# simpleaudio needs the ALSA dev headers on Linux
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y libasound2-dev --quiet
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

mkdir -p samples kits

echo ""
echo "Setup complete."
echo "  Run emulator : .venv/bin/python main.py"
echo "  List MIDI    : .venv/bin/python list_midi.py"
