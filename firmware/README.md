# Firmware

Dumps and patched builds for the SH68F90 (AULA F75 profile). Flash with `sinowisp`
(in `../tools/`). The chip's **bootloader survives erase**, so the board is always
re-flashable even after a bad write.

| File | What |
|------|------|
| `l65-firmware.bin` | **Stock** firmware (61440 B). Rollback target. |
| `l65-firmware-screenbright.bin` | Stock + knob patch: knob rotation in media mode sends Display Brightness ±, not volume. |
| `l65-firmware-sb-nosleep.bin` | **CURRENTLY FLASHED.** Knob patch + wireless fast-doze extended ~3 s → 3+ min. |
| `l65-full.bin` | Full 64 KB dump (firmware + bootloader at 0xF000). For re-importing into Ghidra. |
| `l65-bootloader.bin` | Bootloader region only. |

## Patches

- **Knob → screen brightness** — file offsets `0x259B E9→6F`, `0x259F EA→70`
  (context `74 e9 80 02 74 ea f0` → `74 6f 80 02 74 70 f0`). Media mode only; lighting-mode
  rotation still controls LED brightness; press still = mute.
- **Sleep / no-fast-doze** — 7 operand bytes at `0x844,0x848,0x84d,0x851,0x462,0x466,0x46e`
  set to `0xFF` so the wireless doze counter (0x0A14/0x0A15, decremented in `FUN_CODE_1019`)
  loads ~0xFFFF instead of ~0x0BB8/0x0258/0x00C8. Measured: stays awake 3+ min (was ~3 s).

## Flash commands

```bash
tar xzf ../tools/sinowisp-x86_64-unknown-linux-gnu-v2.1.0.tar.gz   # -> ./sinowisp

# flash a build (example: current combined patch)
./sinowisp write -d aula-f75 --format bin l65-firmware-sb-nosleep.bin

# roll back to stock
./sinowisp write -d aula-f75 --format bin l65-firmware.bin

# read the board back out
./sinowisp read  -d aula-f75 -s full  dump.bin
```

> **Important:** the ISP write factory-resets the *lighting* config (effects/per-key/colour table) —
> the firmware treats a write as a post-update reset. Back up and re-apply your lighting with
> `l65ctl.py` after flashing. A **vendor-app "Restore Defaults"** resets only the config block and
> does **not** touch flashed firmware — but do **not** run any vendor-app *firmware update*, which
> would overwrite these patches with stock.
