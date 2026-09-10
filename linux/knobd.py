#!/usr/bin/env python3
"""
knobd - Womier L65 knob daemon (Linux, tested target: GNOME Wayland).

Turns the volume knob into a context-aware media / scrub / brightness dial.
No keyboard firmware change needed - it just intercepts the knob's evdev events
and re-dispatches them based on gestures + the Left-Shift modifier.

GESTURE MAP  (Left-Shift = modifier)
  rotate                -> volume up/down            (accelerates when spun fast)
  Shift + rotate        -> laptop screen brightness  (accelerates)
  hold knob + rotate    -> scrub / seek media        (nothing if no player)
  press once            -> play/pause  (mute if nothing is playing)
  Shift + press once    -> mute (always)
  double tap            -> next track
  Shift + double tap    -> previous track
  triple tap            -> toggle "app profile"      (stub hook - fill later)
  long press            -> "keyboard profile"        (stub hook - fill later)

How #3 (hold+rotate) and #9 (long press) coexist:
  press down -> if you ROTATE while held  = scrub, long-press cancelled
             -> if you DON'T rotate, held > LONG_PRESS, then release = long press

REQUIRES
  python-evdev                         (pip install evdev  /  distro python3-evdev)
  wpctl (PipeWire) OR pactl OR amixer  -> volume
  playerctl                            -> media control + scrub
  brightnessctl                        -> laptop backlight
  notify-send                          -> on-screen feedback (optional)

The user must be able to read AND grab /dev/input/event* (usually: be in the
'input' group, then re-login). See the setup notes printed by `--help-setup`.
"""

import sys
import time
import shutil
import signal
import argparse
import selectors
import subprocess

try:
    from evdev import InputDevice, list_devices, ecodes
except ImportError:
    sys.exit("python-evdev not installed.  Install:  pip install --user evdev   "
             "(or your distro package python3-evdev)")

# --------------------------------------------------------------------------- #
# Tunables - edit these to taste
# --------------------------------------------------------------------------- #
VENDORS      = {0x258a, 0x3554}   # 0x258a = wired L65, 0x3554 = 2.4G dongle

# The knob emits these on rotation. Stock firmware = volume codes; the screen-
# brightness firmware patch = brightness codes. We accept BOTH so knobd works
# either way and just treats any of them as "one detent" - the daemon alone
# decides what a detent means (volume / brightness / scrub).
ROTATE_UP    = {ecodes.KEY_VOLUMEUP, ecodes.KEY_BRIGHTNESSUP}
ROTATE_DOWN  = {ecodes.KEY_VOLUMEDOWN, ecodes.KEY_BRIGHTNESSDOWN}
PRESS_CODE   = ecodes.KEY_MUTE     # knob press; confirm via --dry-run, change if different

TAP_WINDOW   = 0.28               # s to wait for another tap before resolving
LONG_PRESS   = 0.60              # s held (no rotation) before it counts as long-press

VOL_STEP     = 2                  # % volume per detent (base)
BRI_STEP     = 2                  # % brightness per detent (base)
SEEK_STEP    = 3                  # seconds seek per detent (base)

# Acceleration: gap between detents (s) -> step multiplier. Spin fast = bigger jumps.
def accel_mult(dt):
    if dt is None:   return 1
    if dt < 0.045:   return 5
    if dt < 0.090:   return 3
    return 1

SHOW_OSD     = True               # notify-send feedback for discrete actions

# --------------------------------------------------------------------------- #
# Backends (auto-detected)
# --------------------------------------------------------------------------- #
HAVE = {c: shutil.which(c) is not None for c in
        ("wpctl", "pactl", "amixer", "playerctl", "brightnessctl", "notify-send")}

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2)
    except Exception:
        return None

def vol(delta_pct, up):
    sign = "+" if up else "-"
    if HAVE["wpctl"]:
        run(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", f"{delta_pct}%{sign}"])
    elif HAVE["pactl"]:
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{delta_pct}%"])
    elif HAVE["amixer"]:
        run(["amixer", "-q", "set", "Master", f"{delta_pct}%{sign}"])

def mute_toggle():
    if HAVE["wpctl"]:
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    elif HAVE["pactl"]:
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    elif HAVE["amixer"]:
        run(["amixer", "-q", "set", "Master", "toggle"])

def media_status():
    """Return 'Playing'/'Paused'/'Stopped', or None if no active player."""
    if not HAVE["playerctl"]:
        return None
    r = run(["playerctl", "status"])
    if not r or r.returncode != 0:
        return None
    return r.stdout.strip()

def media(cmd):
    if HAVE["playerctl"]:
        run(["playerctl", cmd])

def scrub(seconds, forward):
    if HAVE["playerctl"]:
        run(["playerctl", "position", f"{seconds}{'+' if forward else '-'}"])

def bright(delta_pct, up):
    if HAVE["brightnessctl"]:
        run(["brightnessctl", "-q", "set", f"{delta_pct}%{'+' if up else '-'}"])

def notify(msg, title="Knob"):
    if SHOW_OSD and HAVE["notify-send"]:
        # the synchronous hint makes each OSD replace the previous one instead of stacking
        run(["notify-send", "-t", "1200",
             "-h", "string:x-canonical-private-synchronous:knobd", title, msg])

# --------------------------------------------------------------------------- #
# Gesture engine
# --------------------------------------------------------------------------- #
class Knob:
    def __init__(self, dry=False):
        self.dry          = dry
        self.shift        = False   # Left-Shift held?
        self.press_t      = None    # monotonic time knob went down, or None
        self.rotated      = False   # did a rotation happen during this press?
        self.taps         = 0       # completed quick taps awaiting resolution
        self.tap_deadline = None    # monotonic time to resolve taps
        self.app_profile  = False   # stub: app-profile toggle state

    def act(self, desc, fn):
        if self.dry:
            print(f"[dry] {desc}")
            return
        fn()

    # -- rotation ---------------------------------------------------------- #
    def on_rotate(self, up, dt):
        m = accel_mult(dt)
        if self.press_t is not None:                 # hold + rotate = scrub
            if not self.rotated:                     # first turn of this hold:
                self.flush_taps()                    #   commit any pending taps first
                self.rotated = True
            if media_status():
                self.act(f"scrub {'+' if up else '-'}{SEEK_STEP*m}s",
                         lambda: scrub(SEEK_STEP * m, up))
        elif self.shift:                             # shift + rotate = brightness
            self.act(f"brightness {'+' if up else '-'}{BRI_STEP*m}%",
                     lambda: bright(BRI_STEP * m, up))
        else:                                        # plain rotate = volume
            self.act(f"volume {'+' if up else '-'}{VOL_STEP*m}%",
                     lambda: vol(VOL_STEP * m, up))

    # -- press / release --------------------------------------------------- #
    def on_press(self):
        self.press_t = time.monotonic()
        self.rotated = False

    def on_release(self):
        if self.press_t is None:
            return
        held = time.monotonic() - self.press_t
        self.press_t = None
        if self.rotated:                             # was a scrub session
            return
        if held >= LONG_PRESS:                       # long press = keyboard profile
            self.flush_taps()
            self.long_press()
            return
        self.taps += 1                               # quick tap - wait for more
        self.tap_deadline = time.monotonic() + TAP_WINDOW

    # -- tap resolution ---------------------------------------------------- #
    def flush_taps(self):
        if self.taps > 0:
            self.resolve_taps()
        else:
            self.tap_deadline = None

    def resolve_taps(self):
        n = self.taps
        self.taps = 0
        self.tap_deadline = None
        if n == 1:
            if self.shift:
                self.act("mute", mute_toggle)
            elif media_status():
                self.act("play/pause", lambda: media("play-pause"))
            else:
                self.act("mute (no media)", mute_toggle)
        elif n == 2:
            if self.shift:
                self.act("previous", lambda: (media("previous"), notify("Previous")))
            else:
                self.act("next", lambda: (media("next"), notify("Next")))
        elif n >= 3:
            self.toggle_app_profile()

    # -- stub hooks (fill in later) --------------------------------------- #
    def toggle_app_profile(self):
        self.app_profile = not self.app_profile
        notify("App profile ON" if self.app_profile else "App profile OFF")

    def long_press(self):
        notify("Keyboard profile (todo)")

# --------------------------------------------------------------------------- #
# Device discovery
# --------------------------------------------------------------------------- #
def find_devices():
    """Return (grab_list, monitor_list).
    grab_list    = knob's consumer node (has VOLUMEUP+MUTE) - we grab it.
    monitor_list = nodes with LEFTSHIFT we don't already grab - read only."""
    grab, mon = [], []
    for path in list_devices():
        try:
            d = InputDevice(path)
        except Exception:
            continue
        if d.info.vendor not in VENDORS:
            continue
        caps = set(d.capabilities().get(ecodes.EV_KEY, []))
        # the knob's consumer node is the one carrying a rotation code
        if (ROTATE_UP | ROTATE_DOWN) & caps:
            grab.append(d)
        elif ecodes.KEY_LEFTSHIFT in caps:
            mon.append(d)
    return grab, mon

# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
SETUP_NOTES = """\
knobd setup
-----------
1. Install deps:
     sudo apt install python3-evdev playerctl brightnessctl   # Debian/Ubuntu
     # PipeWire's wpctl is usually already present; else install wireplumber

2. Allow reading + grabbing the keyboard's input device:
     sudo usermod -aG input $USER
     # log out and back in (group change needs a fresh session)

3. Test it (won't touch your typing):
     python3 knobd.py --list          # confirm it finds the L65
     python3 knobd.py --dry-run       # spin/press the knob, watch the log
     python3 knobd.py                 # go live

4. Autostart as a user service (optional):
     mkdir -p ~/.config/systemd/user
     cat > ~/.config/systemd/user/knobd.service <<'EOF'
     [Unit]
     Description=Womier L65 knob daemon
     After=graphical-session.target
     [Service]
     ExecStart=%h/.local/bin/knobd.py
     Restart=on-failure
     [Install]
     WantedBy=default.target
     EOF
     install -Dm755 knobd.py ~/.local/bin/knobd.py
     systemctl --user daemon-reload
     systemctl --user enable --now knobd.service
"""

def main():
    ap = argparse.ArgumentParser(description="Womier L65 knob daemon")
    ap.add_argument("--list", action="store_true", help="list detected devices and exit")
    ap.add_argument("--dry-run", action="store_true", help="log gestures, execute nothing")
    ap.add_argument("--help-setup", action="store_true", help="print install/setup notes")
    args = ap.parse_args()

    if args.help_setup:
        print(SETUP_NOTES)
        return

    grab_devs, mon_devs = find_devices()

    if args.list:
        for d in grab_devs:
            print(f"GRAB    {d.path}  {d.name}  vendor={hex(d.info.vendor)}")
        for d in mon_devs:
            print(f"MONITOR {d.path}  {d.name}  vendor={hex(d.info.vendor)}")
        if not grab_devs and not mon_devs:
            print("no Womier L65 devices found - is it plugged in / dongle in?")
        return

    if not grab_devs:
        sys.exit("No L65 knob device found (needs VOLUMEUP+MUTE). "
                 "Run 'python3 knobd.py --list'.")

    knob = Knob(dry=args.dry_run)
    sel = selectors.DefaultSelector()

    for d in grab_devs:
        try:
            d.grab()
        except Exception as e:
            print(f"warn: could not grab {d.path}: {e} (run in 'input' group)")
        sel.register(d, selectors.EVENT_READ)
    for d in mon_devs:
        sel.register(d, selectors.EVENT_READ)

    def cleanup(*_):
        for d in grab_devs:
            try:
                d.ungrab()
            except Exception:
                pass
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    backends = ", ".join(k for k, v in HAVE.items() if v) or "NONE (nothing will happen!)"
    print(f"knobd running on: {', '.join(d.name for d in grab_devs)}")
    print(f"backends: {backends}")
    if args.dry_run:
        print("DRY RUN - no actions executed. Ctrl-C to quit.")

    last_rot = None
    while True:
        timeout = None
        if knob.tap_deadline is not None:
            timeout = max(0.0, knob.tap_deadline - time.monotonic())

        for key, _ in sel.select(timeout):
            dev = key.fileobj
            try:
                for ev in dev.read():
                    if ev.type != ecodes.EV_KEY:
                        continue
                    code, val = ev.code, ev.value

                    if code == ecodes.KEY_LEFTSHIFT:
                        if val == 1:
                            knob.shift = True
                        elif val == 0:
                            knob.shift = False
                        continue

                    # act on key-down (val==1); handle knob release separately
                    if val != 1:
                        if code == PRESS_CODE and val == 0:
                            knob.on_release()
                        continue

                    if code in ROTATE_UP:
                        now = time.monotonic()
                        knob.on_rotate(True, (now - last_rot) if last_rot else None)
                        last_rot = now
                    elif code in ROTATE_DOWN:
                        now = time.monotonic()
                        knob.on_rotate(False, (now - last_rot) if last_rot else None)
                        last_rot = now
                    elif code == PRESS_CODE:
                        knob.on_press()
            except OSError:
                pass

        if knob.tap_deadline is not None and time.monotonic() >= knob.tap_deadline:
            knob.resolve_taps()

if __name__ == "__main__":
    main()
