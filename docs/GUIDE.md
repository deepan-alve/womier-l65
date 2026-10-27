# Womier L65 — complete Linux guide

Everything needed to run the keyboard from Linux: the knob daemon, lighting/remap control,
and firmware flashing. Tested target: **GNOME Wayland**.

- [1. First-time setup](#1-first-time-setup)
- [2. Permissions (udev + groups)](#2-permissions-udev--groups)
- [3. Knob daemon (knobd.py)](#3-knob-daemon-knobdpy)
- [4. Lighting, colours & remap (l65ctl.py)](#4-lighting-colours--remap-l65ctlpy)
- [5. Firmware flashing (sinowisp)](#5-firmware-flashing-sinowisp)
- [6. Factory reset](#6-factory-reset)
- [7. Troubleshooting](#7-troubleshooting)
- [8. Reference tables](#8-reference-tables)

---

## 1. First-time setup

Clone (private repo — authenticate with `gh auth login` or your SSH key first):

```bash
git clone https://github.com/deepan-alve/womier-l65.git
cd womier-l65
```

Install dependencies (Debian/Ubuntu; adjust for your distro):

```bash
sudo apt install python3-evdev playerctl brightnessctl
```

- `python3-evdev` — knob daemon (can also `pip install --user evdev`)
- `playerctl` — media control + scrub
- `brightnessctl` — laptop backlight
- `wpctl` (PipeWire) is usually already present; else install `wireplumber`. `pactl`/`amixer` also work.
- `notify-send` (usually preinstalled) — on-screen feedback

`l65ctl.py` needs **no** Python packages — pure `hidraw`. `numpy` is optional and not required.

---

## 2. Permissions (udev + groups)

Two different access needs:

**a) The knob daemon reads/grabs `/dev/input/event*`** → join the `input` group, then log out/in:

```bash
sudo usermod -aG input $USER
```

**b) `l65ctl.py` talks to the keyboard over `hidraw`** → install the udev rule (no sudo needed after):

```bash
sudo cp udev/60-womier-l65.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

(The rule grants your session access to both `258a:010c` wired and `3554:fa09` dongle. Re-plug the
keyboard/dongle once after applying.)

**c) Firmware flashing** (`sinowisp`) needs raw USB and is simplest with `sudo` — see section 5.

---

## 3. Knob daemon (knobd.py)

Turns the volume knob into a context-aware media/scrub/brightness dial. It **grabs only the knob's
media node** (so GNOME doesn't double-act) and watches **Left-Shift / Left-Ctrl / Left-Alt** read-only
(typing untouched). It accepts either volume or brightness rotation codes, so it works whether or not
the screen-brightness firmware patch is flashed. It re-scans every few seconds, so it follows the
keyboard across replugs and wired ↔ dongle switches.

### Gesture map (modifiers = Left-Shift / Left-Ctrl / Left-Alt)

| Gesture | Action | If nothing playing |
|---|---|---|
| Rotate | Volume ± (accelerates when spun fast) | — |
| Shift + rotate | Scrub / seek | nothing |
| Ctrl + rotate | Laptop brightness ± (native GNOME OSD) | — |
| Alt + rotate | Assistant trigger, published over MQTT *(only with `--mqtt-host`)* | — |
| Press once | Play / Pause | Mute |
| Shift + press once | Mute (always) | — |
| Double tap | Next track | — |
| Shift + double tap | Previous track | — |
| Triple tap | Next software profile (`APP_PROFILES`) | — |
| Long press (1.2 s) | Key lighting: dim dark green ↔ off (`LIGHTING_PRESETS`) | — |

Scrub is on Shift rather than hold+rotate because the knob's consumer report has a single usage slot:
rotating while held makes the kernel see a release, so hold+rotate can't be detected.

**Optional MQTT / Home Assistant:** `--mqtt-host HOST [--mqtt-user U --mqtt-password-file F]` publishes
every gesture as an HA device trigger (needs `pip install paho-mqtt`). Off by default.

`linux/knobprobe.py` dumps raw knob events, which is useful if your unit sends different codes.

### Run

```bash
python3 linux/knobd.py --list        # confirm it finds the L65 (prints device names)
python3 linux/knobd.py --dry-run     # spin/press the knob — logs gestures, executes nothing
python3 linux/knobd.py               # go live
python3 linux/knobd.py --help-setup  # built-in install/autostart notes
```

> On first run, do `--dry-run` and confirm the **press** logs as a tap (i.e. it's `KEY_MUTE`). If the
> press shows a different code, change `PRESS_CODE` near the top of `linux/knobd.py`.

### Autostart (systemd user service)

```bash
install -Dm755 linux/knobd.py ~/.local/bin/knobd.py
mkdir -p ~/.config/systemd/user
cp systemd/knobd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now knobd.service
systemctl --user status knobd.service     # check it's running
journalctl --user -u knobd.service -f     # watch logs
```

### Tuning

Edit the constants at the top of `linux/knobd.py`:

| Constant | Meaning | Default |
|---|---|---|
| `TAP_WINDOW` | seconds to wait for another tap | 0.28 |
| `LONG_PRESS` | seconds held (no rotation) = long press | 1.2 |
| `VOL_STEP` / `BRI_STEP` | % per detent | 2 / 2 |
| `SEEK_STEP` | seconds seek per detent | 3 |
| `accel_mult(dt)` | spin-speed → step multiplier (×5 / ×3 / ×1) | — |
| `PRESS_CODE` | evdev code for the knob press | `KEY_MUTE` |

---

## 4. Lighting, colours & remap (l65ctl.py)

Auto-detects the connection (wired first, else dongle). Force with `--wired` / `--wireless`.
**Every write auto-backs-up first** to `~/.cache/l65ctl/backup-*.bin` — undo with `restore`.

### What works over which transport

| Feature | Wired | Dongle |
|---|---|---|
| effect / brightness / speed / side strip / tap / sleep / debounce | ✅ | ✅ |
| custom effect colours (palette) | ✅ | ✅ |
| key / knob **remap** | ✅ | ✅ (layer 0 only) |
| **per-key** colours (each key independent) | ✅ | ❌ |
| realtime frame / music | ✅ | ❌ |
| battery level | — | ✅ |

Dongle note: the keyboard fast-dozes when idle — if a wireless command times out ("asleep"), **press a key**
and retry. The flashed sleep patch keeps it awake ~3 min.

### Commands

```bash
# inspect
python3 linux/l65ctl.py dump                    # current config + which transport
python3 linux/l65ctl.py effects                 # list effect names/numbers
python3 linux/l65ctl.py battery                 # wireless only

# effect / brightness / speed / side strip / globals   (wired + wireless)
python3 linux/l65ctl.py set --effect respire --brightness 2 --speed 0 --color red
python3 linux/l65ctl.py set --side-mode breathing --side-color cyan
python3 linux/l65ctl.py set --tap 180 --sleep 10 --debounce 2      # tap in ms, sleep in minutes
python3 linux/l65ctl.py set --knob media                            # or: lighting

# custom effect colour (writes a palette slot, points the effect at it)  (wired + wireless)
python3 linux/l65ctl.py colors --rgb 8000ff --effect fixed_on --slot 0
python3 linux/l65ctl.py colors                                      # (no --rgb) print the palette

# remap keys / knob press   (WIRED only - a dongle write overwrites the Fn layer)
python3 linux/l65ctl.py remap knob=play_pause caps=esc
python3 linux/l65ctl.py remap --list                               # all key names + actions

# per-key colours   (WIRED only)
python3 linux/l65ctl.py keys --all blue w=red a=red s=red d=red
python3 linux/l65ctl.py keys --list                               # all key names

# realtime frame   (WIRED only)
python3 linux/l65ctl.py frame --all 8000ff --seconds 3

# undo any write
python3 linux/l65ctl.py restore ~/.cache/l65ctl/backup-cfg-YYYYMMDD-HHMMSS.bin
```

`set` value ranges: `--brightness`/`--speed`/`--side-brightness`/`--side-speed` 0–4, `--tap` 0–255 ms
(0 = off), `--sleep` 0–127 min, `--debounce` 1–8, `--color` 0–7 or a name. Colours accept `RRGGBB`,
`#RRGGBB`, or names (red green blue yellow pink cyan white orange purple off).

Remap actions: any key (`a`, `f5`, `enter`), combos (`ctrl+shift+s`), media keys
(`mute vol_up vol_down play_pause next prev stop calculator browser`), raw
(`fn disabled knob_default brightness_up brightness_down effect_next`), or `hex:XXXXXXXX`.

---

## 5. Firmware flashing (sinowisp)

Flashing works on Linux with the included binary. **Two conditions:**

1. **WIRED only** — the ISP/bootloader is on the USB interface; the dongle can't flash the main chip.
   Flip the switch to wired and plug the cable in.
2. **Raw USB access** — run with `sudo` (or add a plugdev udev rule).

Extract the tool:

```bash
tar xzf tools/sinowisp-x86_64-unknown-linux-gnu-v2.1.0.tar.gz
chmod +x sinowisp
```

Flash / roll back / read:

```bash
# re-apply the current combined patch (knob->brightness + extended sleep)
sudo ./sinowisp write -d aula-f75 --format bin firmware/l65-firmware-sb-nosleep.bin

# roll back to stock
sudo ./sinowisp write -d aula-f75 --format bin firmware/l65-firmware.bin

# read the board out (for a fresh dump / Ghidra)
sudo ./sinowisp read -d aula-f75 -s full dump.bin
```

**After any flash the lighting config is factory-reset** (the firmware treats a write as a post-update
reset). Re-apply your look with `l65ctl.py set ...` / `colors ...`. The **bootloader survives erase**, so
even a bad write is always recoverable.

Editing a patch value (e.g. a different sleep timeout): copy a `.bin`, hex-edit the documented bytes
(see [`../firmware/README.md`](../firmware/README.md)), and flash the copy. Finding *new* patch points:
re-import `firmware/l65-full.bin` into Ghidra (the project DB isn't in the repo, but the dump is).

⚠️ Never run the **Windows vendor app's "firmware update"** — it overwrites these patches with stock
(you'd lose the sleep fix). The vendor app's *"Restore Defaults"* is fine (config only).

---

## 6. Factory reset

- **Config** (effects, tap timing, debounce, key/knob remaps, colours): either the Windows vendor app's
  **"Restore Defaults"**, or from Linux write a saved/known-good config with `l65ctl.py restore`, or just
  `l65ctl.py set ...` the values you want. This does **not** touch flashed firmware.
- **Firmware**: flash `firmware/l65-firmware.bin` (stock) — see section 5.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `knobd --list` finds nothing | Keyboard/dongle plugged in? In the `input` group (log out/in)? |
| knob press does nothing in `--dry-run` | Press isn't `KEY_MUTE` — note the code shown and set `PRESS_CODE` in `knobd.py`. |
| rotate does nothing | Check backend line on startup — need one of `wpctl`/`pactl`/`amixer`. |
| brightness doesn't change | `brightnessctl` installed? Laptop panel only (external monitors need `ddcutil`, not wired here). |
| next/prev/play do nothing | `playerctl` installed and an MPRIS player running? |
| GNOME still changes volume too | The daemon didn't grab the device — run in the `input` group so `EVIOCGRAB` succeeds. |
| `l65ctl` "permission denied" | Install the udev rule (section 2b), re-plug. |
| `l65ctl --wireless` "asleep" | Press a key to wake the keyboard, retry. |
| `sinowisp` can't find the board | Ensure wired + `sudo`; if still stuck, re-plug (bootloader entry) and retry. |

---

## 8. Reference tables

**Devices:** wired `258a:010c` (SH68F90), dongle `3554:fa09` (BK3632 "Compx" receiver).

**Config block offsets** (same wired/wireless): `0x03` debounce (stage−1), `0x09` self-define flag,
`0x0A` effect, `0x12–0x15` side strip mode/color/brightness/speed, `0x16` tap ms, `0x18` sleep (min×2),
`0x1A` knob mode (0 media / 1 lighting), `0x38+2n` effect n brightness, `0x39+2n` (speed<<4)|color-slot,
`0x75` self-define brightness, `0x7E` end marker `5A A5`.

**Wireless command map:** config `0x04`/read `0x44`, palette `0x09`/`0x49` (490 B), matrix `0x01`/`0x41`
(504 B), battery `0x4A`. Read code = write code | `0x40`.

**Wired command map:** config `0x04`/`0x84`, per-key `0x06`/`0x86` (378 B planar), palette `0x0A`/`0x8A`
(512 B), matrix `0x03`/`0x83` (504 B), realtime `0x08`, macro `0x05`/`0x85`.

**Firmware patch offsets:** knob→brightness `0x259B E9→6F`, `0x259F EA→70`; sleep — bytes at
`0x844,0x848,0x84d,0x851,0x462,0x466,0x46e` set to `0xFF`. Full details in `firmware/README.md`.
