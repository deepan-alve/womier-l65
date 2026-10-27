# Womier L65 — Linux control, firmware & reverse engineering

Everything you need to work on the **Womier L65** wired/wireless keyboard without the
Windows vendor app: lighting, per-key RGB, key/knob remap, battery, firmware dumps and
patches, a flasher, a knob daemon, and the full reverse-engineering trail behind it.

Hardware: AULA F75 platform, SinoWealth **SH68F90** 8051 MCU, Beken **BK3632** 2.4G radio.
USB IDs `258a` (wired) and `3554` (2.4G dongle).

📖 **Start here: [docs/GUIDE.md](docs/GUIDE.md)** — setup, permissions, knob daemon,
lighting/remap, firmware flashing, factory reset, troubleshooting.

> [!WARNING]
> Flashing firmware can brick your keyboard. The SH68F90 ISP bootloader is not touched
> by the patches here, so a bad flash has always been recoverable on my unit, but you do
> this **at your own risk**. Back up your own board first (`docs/GUIDE.md` §5).

## What's in here

| Path | What |
|------|------|
| `linux/l65ctl.py` | Lighting / palette / remap / per-key RGB / realtime / battery tool (hidraw, no deps). Wired **and** 2.4G dongle. Backs up before every write. |
| `linux/knobd.py` | Knob daemon (evdev): volume, scrub, brightness, media, lighting toggle by gesture. GNOME Wayland. |
| `linux/knobprobe.py` | Prints the raw events your knob sends — for checking a unit that differs from mine. |
| `linux/l65battery.py` | Battery level in the GNOME top bar (AppIndicator). |
| `windows/l65w.ps1` | Windows wireless control tool (PowerShell). |
| `firmware/` | Full flash dump, bootloader, stock firmware and patched builds. See [`firmware/README.md`](firmware/README.md). |
| `tools/` | `sinowisp` v2.1.0 flasher for the SH68F90 ISP (Linux + Windows builds). |
| `udev/` | Rule so `l65ctl.py` / `knobd.py` run without sudo. |
| `systemd/` | User service to autostart the knob daemon. |
| `docs/GUIDE.md` | **Full Linux instructions.** |
| `docs/L65-protocol.md` | HID / RF command protocol reference. |
| `re/` | Reverse-engineering artifacts: Ghidra export scripts, decompiled firmware C, decompiled `sinowisp` source. |

## Quick start on Linux

```bash
sudo apt install python3-evdev playerctl brightnessctl   # deps for the knob daemon
sudo cp udev/60-womier-l65.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
sudo usermod -aG input $USER                             # then log out/in

# lighting / remap / per-key
python3 linux/l65ctl.py dump
python3 linux/l65ctl.py effects
python3 linux/l65ctl.py battery          # over the dongle

# knob daemon
python3 linux/knobd.py --list            # confirm it finds the L65
python3 linux/knobd.py --dry-run         # spin/press the knob, watch the log
python3 linux/knobd.py                   # go live (systemd/ for autostart)
```

### Knob gestures (`knobd.py`)

| Gesture | Action |
|---|---|
| Rotate | Volume ± (accelerates when spun fast) |
| Shift + rotate | Scrub / seek media |
| Ctrl + rotate | Laptop brightness ± |
| Press / Shift + press | Play-pause (mute if nothing plays) / Mute |
| Double tap / Shift + double tap | Next / previous track |
| Triple tap | Next software profile |
| Long press | Key lighting dim green ↔ off |

Optional: `--mqtt-host` publishes every gesture to MQTT as a Home Assistant device trigger.

## What works over which transport

| Feature | Wired (USB) | Wireless (2.4G dongle) |
|---|---|---|
| Config: effect, brightness, speed, side strip, sleep/tap/debounce | ✅ | ✅ (`0x04/0x44`) |
| Effect colour palette (7 shared colours/effect) | ✅ | ✅ (`0x09/0x49`) |
| Key + knob **remap** (key matrix) | ✅ | ❌ writes land on the Fn layer — refused |
| **Per-key** RGB (every key independent) | ✅ (`0x06`) | ❌ hardware limit |
| Realtime frame streaming | ✅ (`0x08/0x88`) | ❌ |
| Battery level | — | ✅ (`0x4A`) |
| Music sync | Windows app only | ❌ |

Per-key colour and realtime are **wired-only**: the dongle only relays the
config/palette/matrix commands, confirmed from both directions. That can't be fixed
without dumping the dongle's firmware, which hasn't been done.

## Firmware

`firmware/` holds a full 64 KB read-out of my L65 plus patched builds:

- **knob → screen brightness** — the knob sends brightness codes instead of volume.
- **no-sleep** — the 2.4G link stays awake 3+ min instead of ~3 s, so multi-step
  wireless operations are reliable.

Details, offsets and flash commands are in [`firmware/README.md`](firmware/README.md).

## Reverse engineering

The 64 KB dump was analysed with Ghidra 12.1.3 (headless). The Ghidra project database
isn't committed (73 MB, re-importable from `firmware/l65-full.bin`). The useful outputs
are in `re/`: decompiled firmware C (`re/exports/`), the export scripts (`re/scripts/`),
and the decompiled `sinowisp` flasher (`re/sinowisp-src/`).

## Contributing

Issues and PRs are welcome — especially captures from other L65 revisions, other
AULA F75-platform boards, or the 2.4G dongle firmware.

## Legal / takedown

This is an independent interoperability project. It isn't affiliated with or endorsed
by Womier, AULA, SinoWealth or Beken. All trademarks belong to their owners.

The firmware images under `firmware/`, the decompiled output under `re/`, and the
`sinowisp` builds under `tools/` belong to their respective owners. They're published
only so owners of this keyboard can back up, repair and interoperate with their own
hardware. The [MIT license](LICENSE) covers only the original code and docs in this repo.

**If you are a rights holder and want any of this material removed, contact
[contact@deepanalve.dev](mailto:contact@deepanalve.dev) or open an issue, and it will
be taken down promptly.**
