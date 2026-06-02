#!/usr/bin/env bash
set -e

# Install PortAudio (required by sounddevice)
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y libportaudio2 portaudio19-dev --quiet
elif command -v brew &>/dev/null; then
    brew install portaudio
else
    echo "Warning: could not install PortAudio automatically."
    echo "  macOS: install Homebrew (brew.sh) then re-run."
    echo "  Linux: sudo apt-get install libportaudio2 portaudio19-dev"
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

mkdir -p samples kits

echo ""
echo "Setup complete."
echo "  Run emulator : .venv/bin/python main.py"
echo "  List MIDI    : .venv/bin/python list_midi.py"
