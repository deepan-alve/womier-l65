# Womier L65 — Linux control & reverse engineering

Full Linux control of the **Womier L65** wired/wireless keyboard (AULA F75 platform,
SinoWealth **SH68F90** 8051 MCU, Beken **BK3632** 2.4G radio), reverse-engineered from
the Windows vendor app. Lighting, per-key RGB, key/knob remap, firmware patches, plus a
userspace **knob daemon** that turns the volume knob into a context-aware media dial.

> Personal project on my own hardware. Private repo — the `firmware/` dumps and the
> decompiled reference under `re/` are from my own device for my own use.

📖 **Full step-by-step instructions: [docs/GUIDE.md](docs/GUIDE.md)** — setup, permissions, knob daemon,
lighting/remap, firmware flashing, factory reset, troubleshooting.

## Layout

| Path | What |
|------|------|
| `linux/knobd.py`  | Knob daemon (evdev) — volume/scrub/brightness/media by gesture. **GNOME Wayland.** |
| `linux/l65ctl.py` | Lighting/remap/per-key tool (hidraw, no deps). Wired **and** 2.4G dongle. |
| `windows/l65w.ps1`| Windows wireless control tool (PowerShell). |
| `firmware/`       | Firmware dumps + patched builds. See `firmware/README.md`. |
| `tools/`          | `sinowisp` flasher (Linux + Windows builds) for the SH68F90 ISP. |
| `udev/`           | hidraw udev rule so `l65ctl.py` runs without sudo. |
| `systemd/`        | user service to autostart the knob daemon. |
| `docs/GUIDE.md`   | **Full Linux instructions** (start here). |
| `docs/L65-protocol.md` | HID/RF protocol reference. |
| `re/`             | Reverse-engineering artifacts: Ghidra export scripts, decompiled firmware C, decompiled `sinowisp` Rust. |

## Quick start on Linux

```bash
sudo apt install python3-evdev playerctl brightnessctl   # deps for the daemon
sudo usermod -aG input $USER                             # then log out/in

# knob daemon
python3 linux/knobd.py --list       # confirm it finds the L65
python3 linux/knobd.py --dry-run    # spin/press the knob, watch the log
python3 linux/knobd.py              # go live   (--help-setup for autostart)

# lighting / remap (needs a udev rule for hidraw — see l65ctl.py docstring)
python3 linux/l65ctl.py dump
python3 linux/l65ctl.py effects
```

### Knob gesture map (`knobd.py`, modifier = Left-Shift)

| Gesture | Action | If no media |
|---|---|---|
| Rotate | Volume ± (accelerates) | — |
| Shift + rotate | Laptop brightness ± | — |
| Hold + rotate | Scrub / seek | nothing |
| Press once | Play/Pause | Mute |
| Shift + press once | Mute | — |
| Double tap | Next track | — |
| Shift + double tap | Previous track | — |
| Triple tap | Toggle app profile *(stub)* | — |
| Long press | Keyboard profile *(stub)* | — |

The daemon **grabs only the knob's consumer node** (so GNOME doesn't double-act) and
watches Left-Shift read-only (typing untouched). It accepts either volume **or** brightness
rotation codes, so it works whether or not the screen-brightness firmware patch is flashed.

## What works over which transport

| Feature | Wired (USB) | Wireless (2.4G dongle) |
|---|---|---|
| Config: effect, brightness, speed, side strip, sleep/tap/debounce | ✅ | ✅ (`0x04/0x44`) |
| Effect colour palette (7 shared colours/effect) | ✅ | ✅ (`0x09/0x49`) |
| Key + knob **remap** (key matrix) | ✅ | ✅ layer 0 (`0x01/0x41`) |
| **Per-key** RGB (every key independent) | ✅ (`0x06`) | ❌ hardware limit |
| Realtime frame streaming | ✅ (`0x08/0x88`) | ❌ |
| Music sync | Windows app only | ❌ |

Per-key colour and realtime are **wired-only** — the dongle relays only the config/palette/matrix
command vocabulary, confirmed from both directions. Not fixable without dongle firmware (undumped chip).

Wireless note: the keyboard fast-dozes when idle; the flashed sleep patch extends that to 3+ min so
multi-step wireless ops stay reliable (hold a key to wake if it's been idle).

## Reverse engineering

Ghidra 12.1.3 (headless) on the 64 KB firmware dump. The Ghidra *project database* isn't in the repo
(73 MB, re-importable from `firmware/l65-full.bin`); the useful outputs are in `re/`:
decompiled firmware C (`re/exports/`), the export scripts (`re/scripts/`), and the decompiled
`sinowisp` flasher for reference (`re/sinowisp-src/`).
