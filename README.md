# Groovebox Pi

A self-contained hardware groovebox built on a Raspberry Pi 3B with a Pimoroni Pirate Audio 3W Stereo Amp HAT. The 240 × 240 px LCD, four hardware buttons, and onboard amplifier are all driven from a single HAT that slots directly onto the Pi's GPIO header.

---

## Hardware bill of materials

| Item                                    | Notes                               |
| --------------------------------------- | ----------------------------------- |
| Raspberry Pi 3B (or newer)              | Pi 3B+ / 4B also work               |
| Pimoroni Pirate Audio 3W Stereo Amp HAT | Includes 240×240 LCD + 4 buttons    |
| Passive speakers, 3 W or less           | 4 Ω or 8 Ω recommended              |
| Akai MPK Mini MKII                      | USB MIDI pad/keyboard controller    |
| MicroSD card, 8 GB+                     | Class 10 / A1 speed class           |
| Power supply                            | Under-voltage causes audio glitches |

---

## Raspberry Pi OS setup (first time)

### 1 Flash the SD card

1. Download **Raspberry Pi Imager** from [raspberrypi.com/software](https://www.raspberrypi.com/software/).
2. Choose **Raspberry Pi OS Lite (64-bit)** — no desktop needed.
3. Click the **gear icon** (Advanced Options) before writing:
   - Set hostname: `groovebox`
   - Enable SSH
   - Set username and password (e.g. `pi` / `groovebox`)
   - Configure WiFi (SSID + password)
4. Write the card and insert it into the Pi.

### 2 First boot and SSH

```bash
# From your Mac / PC
ssh pi@groovebox.local
# If .local doesn't resolve, find the IP via your router admin page
```

Allow ~60 s for the first boot to complete.

### 3 Clone and run setup

```bash
git clone https://github.com/YOUR_USERNAME/groovebox-pi.git
cd groovebox-pi
bash setup.sh --pi
```

The `--pi` flag:

- Enables **SPI** (ST7789 display) and **I2S** (Pirate Audio amp) in `/boot/firmware/config.txt`
- Loads the `hifiberry-dac` overlay (compatible with Pirate Audio)
- Disables the onboard BCM2835 audio (it conflicts with I2S)
- Writes a minimal `/etc/asound.conf` so `sounddevice` finds the amp
- Installs the `ST7789` Python library and `gpiozero`
- Creates and enables a **systemd service** that auto-starts the groovebox on boot

### 4 Reboot

```bash
sudo reboot
```

After reboot, the groovebox will start automatically and appear on the LCD.  
To check it started correctly:

```bash
sudo systemctl status groovebox
sudo journalctl -u groovebox -f   # live log
```

---

## Running manually (development / HDMI debug)

```bash
# With HDMI monitor + keyboard attached
.venv/bin/python main.py

# Headless (LCD only, no HDMI)
.venv/bin/python main.py --headless
```

The app detects automatically: if `DISPLAY` is set it opens a tkinter window (and mirrors to the LCD if fitted). If `DISPLAY` is not set it falls back to LCD-only.

---

## Adding samples

Copy 44.1 kHz WAV files into the `samples/` directory. They will appear in the Kits → Instruments pad-assignment screen.

```bash
scp my_kick.wav pi@groovebox.local:~/groovebox-pi/samples/
```

Supported formats: **WAV** (8-bit, 16-bit, 24-bit, 32-bit float). Mono files are automatically up-mixed to stereo. Files at other sample rates are resampled on first load.

---

## Hardware button mapping

The Pirate Audio HAT has four buttons (A, B, X, Y) mapped as follows:

| Button | GPIO (BCM) | Key equivalent |
| ------ | ---------- | -------------- |
| A      | 5          | Up             |
| B      | 6          | Down           |
| X      | 16         | Enter / Select |
| Y      | 24         | Back           |

This gives full navigation of all menus. Play-screen controls (arming loops, BPM, etc.) currently require a keyboard; MIDI mapping for the Akai MPK Mini is planned.

---

## Keyboard reference

### Main menu

| Key   | Action   |
| ----- | -------- |
| ↑ / ↓ | Navigate |
| Enter | Open     |

### Play (loop recorder)

| Key                   | Action                                  |
| --------------------- | --------------------------------------- |
| `1` – `4`             | Arm / prime a loop channel              |
| Hold `1`–`4` (0.7 s)  | Delete that channel                     |
| `x`                   | Mute / unmute selected channel          |
| `o`                   | Toggle overdub mode on selected channel |
| ↑ / ↓                 | Select channel                          |
| ← / →                 | Change loop length (bars)               |
| `-` / `=`             | BPM −1 / +1                             |
| `m`                   | Toggle metronome                        |
| `r`                   | Reset all channels                      |
| `Q W E R` / `A S D F` | Trigger pads 1–8                        |
| Backspace             | Back                                    |

### Sequencer

| Key       | Action                                         |
| --------- | ---------------------------------------------- |
| `Q`–`F`   | Toggle step for that pad row                   |
| ← / →     | Move step cursor                               |
| Space     | Play / stop                                    |
| `-` / `=` | BPM −1 / +1                                    |
| `s`       | Save sequence (prompts for name on first save) |
| `l`       | Load sequence                                  |
| `n`       | Rename current sequence                        |
| Backspace | Back                                           |

### Kits

Navigate with ↑ / ↓ / Enter / Backspace. Within a saved kit, choose **Load**, **Rename**, **Edit Pads** (opens pad assignment), or **Delete**. **Create New** saves the current kit state under a new name.

---

## Troubleshooting

### Settings → Debug screen

Open **Settings → Debug** for a live diagnostic view:

- **Devices** panel — shows the detected default audio output, any MIDI ports, LCD status, and GPIO status. Green = OK, red = not found or error.
- **Last inputs** — a rolling log of the last 12 key presses, MIDI messages, and GPIO button events. Useful for confirming the Akai is being detected and sending data.
- **Test Audio button** — press `Enter` to play a 440 Hz test tone. If you hear it, the audio pipeline is working end-to-end.

---

### No sound

1. **Check the Debug screen** — is the Audio device green? Note the device name.
2. Run the latency test: `.venv/bin/python test_audio_latency.py`
3. Check ALSA sees the card:
   ```bash
   aplay -l
   # Should show: card 0: sndrpihifiberry [snd_rpi_hifiberry_dac]
   ```
4. If the card is missing, verify `/boot/firmware/config.txt` contains:
   ```
   dtparam=i2s=on
   dtoverlay=hifiberry-dac
   dtparam=audio=off
   ```
   Then reboot.
5. Check for under-voltage: `vcgencmd get_throttled` — `0x0` is healthy.

### Display not working

1. Check the Debug screen LCD row (if you have HDMI for debugging).
2. Verify SPI is enabled: `ls /dev/spi*` — should show `/dev/spidev0.0` and `/dev/spidev0.1`.
3. If missing, add `dtparam=spi=on` to config.txt and reboot.
4. Check the HAT is fully seated on the GPIO header (all 40 pins).

### Akai MPK Mini not detected

1. Plug the MPK Mini into a USB port and check the Debug screen — MIDI row should turn green.
2. From the terminal: `.venv/bin/python list_midi.py`  
   Expected output: `MPK mini ...`
3. If missing, check `lsusb` — the device should appear as `AKAI Professional MPK Mini`.
4. Try a different USB cable (micro-USB, not all cables support data).
5. Check the MPK Mini's MIDI output is not set to a specific channel that gets filtered.

### GPIO buttons not working

1. The Debug screen GPIO row shows `gpiozero not installed` or `init failed`.
2. Install: `.venv/bin/pip install gpiozero RPi.GPIO`
3. Confirm the HAT is correctly seated.
4. Test a single button from Python:
   ```python
   from gpiozero import Button
   b = Button(5)  # Button A
   b.wait_for_press()
   print("pressed!")
   ```

### App crashes on startup

Check the service log:

```bash
sudo journalctl -u groovebox -n 50 --no-pager
```

Common causes:

- **`PortAudioError: Error querying device -1`** — audio driver not loaded. Confirm I2S overlay is in config.txt and you've rebooted.
- **`ModuleNotFoundError`** — run `bash setup.sh --pi` again (the venv may be missing packages).
- **`ST7789 init failed`** — SPI not enabled, or HAT not seated.

### Running over SSH (no LCD, no HDMI)

For development without the HAT:

```bash
# On Mac/Linux with X11 forwarding
ssh -X pi@groovebox.local
.venv/bin/python main.py
```

Or with VSCode Remote SSH — the tkinter window will forward to your machine.

---

## Project structure

```
groovebox-pi/
├── main.py                  Entry point (tkinter + headless modes)
├── midi.py                  MIDI input handler
├── setup.sh                 Setup script (add --pi for Pi-specific steps)
├── requirements.txt         Python deps
├── samples/                 WAV sample files (user-supplied)
├── kits/                    Saved kit JSON files
├── sequences/               Saved sequence JSON files
├── state.json               Last-used kit and settings
└── groovebox/
    ├── audio.py             Audio engine (PortAudio stream mixer + WSL bridge)
    ├── constants.py         Display constants and key maps
    ├── event_log.py         Shared input-event ring buffer (for Debug screen)
    ├── hardware.py          ST7789 display + GPIO button abstraction
    ├── kit.py               Kit model + save/load
    ├── looper.py            Loop engine (record, play, overdub, mute)
    ├── sequencer.py         Step sequencer + save/load
    ├── settings.py          App settings model
    └── ui/
        ├── base.py          Screen ABC, NameInputScreen, helpers
        ├── debug_screen.py  Debug / diagnostics screen
        ├── instruments.py   Pad assignment screen
        ├── kits.py          Kit management screens
        ├── looper_screen.py Play (loop recorder) screen
        ├── main_menu.py     Home menu
        ├── sequencer_screen.py Sequencer + save/load screens
        └── settings_screen.py  Settings + Debug entry
```
