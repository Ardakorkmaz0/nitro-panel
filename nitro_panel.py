#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Nitro Panel: a small GTK control panel for Acer Nitro and Predator laptops.

It talks to the Linuwu-Sense kernel module through sysfs. Keyboard, fan and
battery files need the user to be in the linuwu_sense group. The power mode
file is made group-writable by the bundled tmpfiles rule; without it, the
panel falls back to pkexec.

`nitro-panel --daemon` is the optional background service. It applies a
profile when the charger is plugged in or out, and shows the new power mode
when the NitroSense key is pressed.

The other command line options (see --help) are what the Plasma widget
calls. They run without loading GTK, so they stay quick.
"""

import glob
import json
import os
import subprocess
import sys

__version__ = "0.4.0"

APP_ID = "io.github.ardakorkmaz0.NitroPanel"
DAEMON_UNIT = "nitro-panel-daemon.service"
NOTIFY_TIMEOUT_MS = 3000

BASE = "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi"
FOUR_ZONE = f"{BASE}/four_zoned_kb/four_zone_mode"
PER_ZONE = f"{BASE}/four_zoned_kb/per_zone_mode"
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
PLATFORM_CHOICES = "/sys/firmware/acpi/platform_profile_choices"
CONFIG_FILE = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "nitro-panel", "config.json",
)

# (driver mode, label, uses color, uses speed, uses direction)
# Mode 0 (static) is left out: "Zone colors" covers it.
EFFECTS = [
    (1, "Breathing", True, False, False),
    (2, "Neon", False, True, False),
    (3, "Wave", False, True, True),
    (4, "Shifting", True, True, True),
    (5, "Zoom", True, True, False),
    (6, "Meteor", True, True, False),
    (7, "Twinkling", True, True, False),
]

# platform_profile value and the NitroSense mode the driver maps it to
POWER_MODES = [
    ("low-power", "Eco"),
    ("quiet", "Quiet"),
    ("balanced", "Balanced"),
    ("balanced-performance", "Performance"),
    ("performance", "Turbo"),
]
POWER_LABELS = dict(POWER_MODES)

PRESETS = [
    ("Red", "ff0000"),
    ("Orange", "ff4000"),
    ("Blue", "0040ff"),
    ("Purple", "8000ff"),
    ("White", "ffffff"),
]

# Switches only some models expose; each one is shown only when writable.
EXTRA_SWITCHES = [
    ("boot_animation_sound", "Boot animation and sound", None),
    ("lcd_override", "LCD overdrive", "Faster pixel response, may add ghosting"),
]

# Written to the config file the first time, then the user's to change.
DEFAULT_PROFILES = {
    "Gaming": {
        "power": "performance",
        "fans": "auto",
        "keyboard": {"mode": "zones", "zones": ["ff0000"] * 4, "brightness": 100},
    },
    "Quiet": {
        "power": "quiet",
        "fans": "auto",
        "keyboard": {"mode": "zones", "zones": ["ffffff"] * 4, "brightness": 30},
    },
    "Battery saver": {
        "power": "low-power",
        "fans": "auto",
        "keyboard": {"mode": "zones", "zones": ["ffffff"] * 4, "brightness": 0},
    },
}


def log(message):
    print(f"nitro-panel: {message}", file=sys.stderr, flush=True)


def read(path):
    if path is None:
        return None
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def write(path, value):
    with open(path, "w") as f:
        f.write(value)


def writable(path):
    return path is not None and os.access(path, os.W_OK)


def sense_path(name):
    """Path of a NitroSense/PredatorSense setting, or None if this model lacks it."""
    for folder in ("nitro_sense", "predator_sense"):
        path = f"{BASE}/{folder}/{name}"
        if os.path.exists(path):
            return path
    return None


def find_hwmon(name):
    for path in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{path}/name") == name:
            return path
    return None


def find_battery():
    for path in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        return path
    return None


def battery_health(battery):
    """Current full capacity against the design capacity, as text."""
    for kind, unit in (("energy", "Wh"), ("charge", "Ah")):
        full = read(f"{battery}/{kind}_full")
        design = read(f"{battery}/{kind}_full_design")
        if full and design and full.isdigit() and design.isdigit() and int(design):
            percent = round(100 * int(full) / int(design))
            # sysfs reports µWh / µAh
            return (f"Health: {percent}% of original capacity "
                    f"({int(full) / 1e6:.2f} of {int(design) / 1e6:.2f} {unit})")
    return None


def temperature(path):
    value = read(path)
    return f"{int(value) // 1000}°C" if value and value.lstrip("-").isdigit() else "?"


# --- profiles ---------------------------------------------------------------


def load_config():
    config = {
        "profiles": json.loads(json.dumps(DEFAULT_PROFILES)),
        "on_battery": None,
        "on_ac": None,
        "mode_key": False,
        "kb_fine": False,
    }
    try:
        with open(CONFIG_FILE) as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass
    return config


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = f"{CONFIG_FILE}.tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def keyboard_value(keyboard):
    """The sysfs file and value for the keyboard part of a profile."""
    brightness = int(keyboard.get("brightness", 100))
    if keyboard.get("mode", "zones") == "zones":
        return PER_ZONE, f"{','.join(keyboard['zones'])},{brightness}"
    color = keyboard.get("color", "ffffff")
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    speed = keyboard.get("speed", 5)
    direction = keyboard.get("direction", 2)
    return FOUR_ZONE, f"{keyboard['mode']},{speed},{brightness},{direction},{r},{g},{b}"


def fan_value(fans):
    if fans == "auto":
        return "0,0"
    if fans == "max":
        return "100,100"
    cpu, gpu = (int(v) for v in fans)
    # The driver treats 100,100 as max mode; stay in custom mode
    if cpu == 100 and gpu == 100:
        gpu = 95
    return f"{cpu},{gpu}"


def apply_profile(profile, power_fallback=None):
    """Apply a saved profile. Returns a list of problems, empty when all went well."""
    problems = []

    power = profile.get("power")
    if power:
        if power not in (read(PLATFORM_CHOICES) or "").split():
            problems.append(f"{POWER_LABELS.get(power, power)} mode is not available right now")
        else:
            try:
                write(PLATFORM_PROFILE, power)
            except PermissionError:
                if power_fallback:
                    power_fallback(power)
                else:
                    problems.append("no permission to change the power mode")
            except OSError as err:
                problems.append(f"power mode: {err.strerror}")

    steps = []
    try:
        if "fans" in profile and sense_path("fan_speed"):
            steps.append(("fans", sense_path("fan_speed"), fan_value(profile["fans"])))
        if "keyboard" in profile and os.path.exists(PER_ZONE):
            steps.append(("keyboard", *keyboard_value(profile["keyboard"])))
    except (KeyError, TypeError, ValueError):
        problems.append("the profile data is damaged")
    for name, path, value in steps:
        try:
            write(path, value)
        except OSError as err:
            problems.append(f"{name}: {err.strerror}")
    return problems


# --- command line -----------------------------------------------------------

CLI_USAGE = """\
usage: nitro-panel [OPTION]

Without an option, opens the panel window.

  --status                print the current state as JSON
  --mode MODE             set the power mode: eco, quiet, balanced, performance, turbo
  --profile NAME          apply a saved profile
  --kb-brightness 0-100   set the keyboard light brightness, keeping its colors
  --battery-limit on|off  stop charging at 80%
  --kb-fine on|off        brightness in steps of 1 instead of off/25/50/75/100%
  --kb-timeout on|off     turn the keyboard light off after 30 s without typing
  --daemon               run the background service
  --version               print the version
"""

CLI_OPTIONS = {"--status", "--mode", "--profile", "--kb-brightness", "--battery-limit",
               "--kb-fine", "--kb-timeout", "--version", "--help", "-h"}

MODE_ALIASES = {label.lower(): mode for mode, label in POWER_MODES}


class CliError(Exception):
    pass


def keyboard_state():
    """The current keyboard lighting as a profile part, or None without one."""
    try:
        mode, speed, brightness, direction, r, g, b = (int(v) for v in read(FOUR_ZONE).split(","))
        if mode != 0:
            return {"mode": mode, "speed": max(speed, 1),
                    "direction": direction if direction in (1, 2) else 2,
                    "color": f"{r:02x}{g:02x}{b:02x}", "brightness": brightness}
        *zones, brightness = read(PER_ZONE).split(",")
        return {"mode": "zones", "zones": zones, "brightness": int(brightness)}
    except (AttributeError, ValueError):
        return None


def status():
    hwmon = find_hwmon("acer")
    choices = (read(PLATFORM_CHOICES) or "").split()
    keyboard = keyboard_state()
    limiter = read(sense_path("battery_limiter"))
    config = load_config()
    timeout_path = sense_path("backlight_timeout")
    timeout = read(timeout_path) if writable(timeout_path) else None

    def sensor(name, scale=1):
        value = read(f"{hwmon}/{name}") if hwmon else None
        return int(value) // scale if value and value.lstrip("-").isdigit() else None

    return {
        "version": __version__,
        "available": os.path.exists(BASE),
        "writable": writable(PER_ZONE) or writable(sense_path("fan_speed")),
        "mode": read(PLATFORM_PROFILE),
        "modes": [{"id": m, "label": label, "available": m in choices} for m, label in POWER_MODES],
        "keyboard_brightness": keyboard["brightness"] if keyboard else None,
        "keyboard_fine": bool(config.get("kb_fine")),
        # None when the timeout cannot be changed (missing, root-only or unknown)
        "keyboard_timeout": {"1": True, "0": False}.get(timeout),
        "battery_limit": None if limiter is None else limiter == "1",
        "sensors": {
            "cpu_temp": sensor("temp1_input", 1000),
            "gpu_temp": sensor("temp2_input", 1000),
            "cpu_fan": sensor("fan1_input"),
            "gpu_fan": sensor("fan2_input"),
        },
        "profiles": sorted(config["profiles"], key=str.lower),
    }


def pkexec_power(mode):
    """Write the power mode through polkit. Returns an error message or None."""
    tee = next((p for p in ("/usr/bin/tee", "/bin/tee") if os.path.exists(p)), "tee")
    result = subprocess.run(["pkexec", tee, PLATFORM_PROFILE], input=mode, text=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return f"could not change the power mode: {result.stderr.strip() or 'cancelled'}"
    return None


def set_power_mode(mode):
    mode = MODE_ALIASES.get(mode.lower(), mode)
    if mode not in (read(PLATFORM_CHOICES) or "").split():
        raise CliError(f"{POWER_LABELS.get(mode, mode)} mode is not available right now")
    try:
        write(PLATFORM_PROFILE, mode)
    except PermissionError:
        error = pkexec_power(mode)
        if error:
            raise CliError(error) from None


def cli(args):
    """Handle the quick command line options. Returns the exit code."""
    option = args[0]
    value = args[1] if len(args) > 1 else None
    try:
        if option in ("--help", "-h"):
            print(CLI_USAGE, end="")
        elif option == "--version":
            print(f"nitro-panel {__version__}")
        elif option == "--status":
            print(json.dumps(status()))
        elif value is None:
            raise CliError(f"{option} needs a value, see --help")
        elif option == "--mode":
            set_power_mode(value)
        elif option == "--profile":
            profiles = load_config()["profiles"]
            if value not in profiles:
                raise CliError(f"there is no profile called {value!r}")
            extra = []

            def fallback(mode):
                error = pkexec_power(mode)
                if error:
                    extra.append(error)

            problems = apply_profile(profiles[value], fallback) + extra
            if problems:
                raise CliError(f"applied {value!r}, except: {'; '.join(problems)}")
        elif option == "--kb-brightness":
            if not value.isdigit() or not 0 <= int(value) <= 100:
                raise CliError("the brightness must be a number from 0 to 100")
            keyboard = keyboard_state()
            if keyboard is None:
                raise CliError("no keyboard lighting found")
            keyboard["brightness"] = int(value)
            write(*keyboard_value(keyboard))
        elif option == "--battery-limit":
            path = sense_path("battery_limiter")
            if path is None:
                raise CliError("this laptop has no battery charge limit")
            if value not in ("on", "off"):
                raise CliError("use --battery-limit on or --battery-limit off")
            write(path, "1" if value == "on" else "0")
        elif option == "--kb-fine":
            if value not in ("on", "off"):
                raise CliError("use --kb-fine on or --kb-fine off")
            config = load_config()
            config["kb_fine"] = value == "on"
            save_config(config)
        elif option == "--kb-timeout":
            path = sense_path("backlight_timeout")
            if path is None:
                raise CliError("this laptop has no keyboard light timeout")
            if value not in ("on", "off"):
                raise CliError("use --kb-timeout on or --kb-timeout off")
            write(path, "1" if value == "on" else "0")
    except CliError as err:
        print(f"nitro-panel: {err}", file=sys.stderr)
        return 1
    except PermissionError:
        print("nitro-panel: permission denied; are you in the linuwu_sense group?", file=sys.stderr)
        return 1
    except OSError as err:
        print(f"nitro-panel: {err.strerror}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__" and sys.argv[1:2] and sys.argv[1] in CLI_OPTIONS:
    sys.exit(cli(sys.argv[1:]))


# Everything below needs GTK or GLib: the panel window and the background service.

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402


def rgba_to_hex(rgba):
    return "".join(f"{round(c * 255):02x}" for c in (rgba.red, rgba.green, rgba.blue))


def hex_to_rgba(value):
    rgba = Gdk.RGBA()
    rgba.parse(f"#{value}")
    return rgba


# --- window helpers ---------------------------------------------------------


def section(title):
    label = Gtk.Label(xalign=0)
    label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    label.set_margin_top(6)
    return label


def dim(text):
    label = Gtk.Label(label=text, xalign=0, wrap=True)
    label.get_style_context().add_class("dim-label")
    return label


def row(title, widget, hint=None):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    labels.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
    if hint:
        small = Gtk.Label(xalign=0, wrap=True)
        small.set_markup(f"<small>{GLib.markup_escape_text(hint)}</small>")
        small.get_style_context().add_class("dim-label")
        labels.pack_start(small, False, False, 0)
    box.pack_start(labels, True, True, 0)
    box.pack_end(widget, False, False, 0)
    widget.set_valign(Gtk.Align.CENTER)
    return box


def page():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(18)
    return box


def linked_radios(items, callback):
    """A row of joined toggle buttons that behave like radio buttons."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
    box.get_style_context().add_class("linked")
    buttons = {}
    group = None
    for key, label in items:
        button = Gtk.RadioButton.new_with_label_from_widget(group, label)
        button.set_mode(False)
        button.connect("toggled", callback, key)
        box.pack_start(button, True, True, 0)
        buttons[key] = button
        group = group or button
    return box, buttons


class NitroPanel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Nitro Panel")
        self.set_default_size(480, 0)
        self.set_icon_name("input-keyboard")

        self._pending = {}
        self._updating = False
        self._info_timer = None
        self.config = load_config()
        self.hwmon = find_hwmon("acer")
        self.battery = find_battery()
        self.has_kb = os.path.exists(PER_ZONE)
        self.backlight_timeout = None

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        if self.has_kb:
            stack.add_titled(self.build_keyboard(), "keyboard", "Keyboard")
        stack.add_titled(self.build_power(), "power", "Power")
        stack.add_titled(self.build_battery(), "battery", "Battery")
        stack.add_titled(self.build_profiles(), "profiles", "Profiles")

        header = Gtk.HeaderBar(show_close_button=True)
        header.set_custom_title(Gtk.StackSwitcher(stack=stack))
        self.set_titlebar(header)

        self.info = Gtk.InfoBar(show_close_button=True, revealed=False)
        self.info.connect("response", lambda bar, _r: bar.set_revealed(False))
        self.info_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.info.get_content_area().add(self.info_label)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(self.info, False, False, 0)
        outer.pack_start(stack, True, True, 0)
        self.add(outer)

        if not os.path.exists(BASE):
            self.show_message(
                "The linuwu_sense kernel module is not loaded. Install Linuwu-Sense first.",
            )
        elif sense_path("fan_speed") and not writable(sense_path("fan_speed")):
            self.show_message(
                "No write access yet. Run: sudo usermod -aG linuwu_sense $USER, "
                "then log out and back in.",
                Gtk.MessageType.WARNING,
            )

        self.load_state()
        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    # --- helpers ----------------------------------------------------------

    def show_message(self, text, kind=Gtk.MessageType.ERROR):
        if self._info_timer:
            GLib.source_remove(self._info_timer)
            self._info_timer = None
        self.info.set_message_type(kind)
        self.info_label.set_text(text)
        self.info.set_revealed(True)
        if kind == Gtk.MessageType.INFO:
            def hide():
                self._info_timer = None
                self.info.set_revealed(False)
                return False
            self._info_timer = GLib.timeout_add_seconds(3, hide)

    def apply(self, path, value):
        try:
            write(path, value)
        except PermissionError:
            self.show_message(
                "Permission denied. Make sure you are in the linuwu_sense group "
                "and have logged in again.",
                Gtk.MessageType.WARNING,
            )
        except OSError as err:
            self.show_message(f"The driver rejected {value!r}: {err.strerror}")

    def debounce(self, key, fn, delay=250):
        """Wait for a slider to settle instead of making a WMI call per step."""
        if self._updating:
            return
        if key in self._pending:
            GLib.source_remove(self._pending[key])

        def run():
            del self._pending[key]
            fn()
            return False

        self._pending[key] = GLib.timeout_add(delay, run)

    # --- keyboard ---------------------------------------------------------

    def build_keyboard(self):
        box = page()

        self.kb_mode = Gtk.ComboBoxText()
        self.kb_mode.append("zones", "Zone colors")
        for mode, label, *_ in EFFECTS:
            self.kb_mode.append(str(mode), label)
        self.kb_mode.set_active_id("zones")
        self.kb_mode.connect("changed", self.on_kb_mode_changed)
        box.pack_start(row("Mode", self.kb_mode), False, False, 0)

        self.zone_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        zones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        self.zone_buttons = []
        for i in range(4):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            button = Gtk.ColorButton(use_alpha=False, title=f"Zone {i + 1}")
            button.set_rgba(hex_to_rgba("ffffff"))
            button.set_size_request(-1, 40)
            button.connect("color-set", lambda *_: self.debounce("kb", self.apply_keyboard, 0))
            col.pack_start(button, False, False, 0)
            col.pack_start(Gtk.Label(label=f"Zone {i + 1}"), False, False, 0)
            zones.pack_start(col, True, True, 0)
            self.zone_buttons.append(button)
        self.zone_box.pack_start(zones, False, False, 0)
        same = Gtk.Button(label="Use zone 1 color everywhere")
        same.connect("clicked", self.on_same_color)
        self.zone_box.pack_start(same, False, False, 0)
        box.pack_start(self.zone_box, False, False, 0)

        self.effect_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.effect_color = Gtk.ColorButton(use_alpha=False, title="Effect color")
        self.effect_color.set_rgba(hex_to_rgba("ffffff"))
        self.effect_color.connect("color-set", lambda *_: self.debounce("kb", self.apply_keyboard, 0))
        self.effect_color_row = row("Color", self.effect_color)
        self.effect_box.pack_start(self.effect_color_row, False, False, 0)

        self.speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 9, 1)
        self.speed.set_size_request(220, -1)
        self.speed.set_value(5)
        self.speed.connect("value-changed", lambda *_: self.debounce("kb", self.apply_keyboard))
        self.speed_row = row("Speed", self.speed)
        self.effect_box.pack_start(self.speed_row, False, False, 0)

        self.direction = Gtk.ComboBoxText()
        self.direction.append("1", "Right to left")
        self.direction.append("2", "Left to right")
        self.direction.set_active_id("2")
        self.direction.connect("changed", lambda *_: self.debounce("kb", self.apply_keyboard, 0))
        self.direction_row = row("Direction", self.direction)
        self.effect_box.pack_start(self.direction_row, False, False, 0)
        box.pack_start(self.effect_box, False, False, 0)

        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.brightness.set_size_request(220, -1)
        self.brightness.set_value(100)
        self.brightness.connect("change-value", self.on_brightness_change)
        self.brightness.connect("value-changed", lambda *_: self.debounce("kb", self.apply_keyboard))
        box.pack_start(row("Brightness", self.brightness, "0 turns the light off"), False, False, 0)

        steps, self.kb_step_buttons = linked_radios(
            [("steps", "Steps"), ("fine", "Fine")], self.on_kb_steps,
        )
        self._updating = True
        self.kb_step_buttons["fine" if self.config.get("kb_fine") else "steps"].set_active(True)
        self._updating = False
        box.pack_start(row("Brightness steps", steps, "Steps: off, 25, 50, 75 and 100%, like NitroSense"),
                       False, False, 0)
        self.update_brightness_steps()

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        for name, color in PRESETS:
            button = Gtk.Button(label=name)
            button.connect("clicked", self.on_preset, color)
            presets.pack_start(button, True, True, 0)
        box.pack_start(section("Quick colors"), False, False, 0)
        box.pack_start(presets, False, False, 0)

        path = sense_path("backlight_timeout")
        if writable(path):
            self.backlight_timeout = Gtk.Switch()
            self.backlight_timeout.connect("notify::active", self.on_switch, path)
            box.pack_start(section("Other"), False, False, 0)
            box.pack_start(
                row("Turn off when idle", self.backlight_timeout,
                    "After 30 seconds without typing. When off, the light stays on."),
                False, False, 0,
            )
        return box

    def on_kb_steps(self, button, key):
        if self._updating or not button.get_active():
            return
        self.config["kb_fine"] = key == "fine"
        self.save()
        self.update_brightness_steps()

    def update_brightness_steps(self):
        self.brightness.clear_marks()
        if self.config.get("kb_fine"):
            self.brightness.set_increments(1, 10)
        else:
            self.brightness.set_increments(25, 25)
            for value in (0, 25, 50, 75, 100):
                self.brightness.add_mark(value, Gtk.PositionType.BOTTOM, None)

    def on_brightness_change(self, scale, _scroll, value):
        """In Steps mode, snap whatever the user does to the nearest 25%."""
        if self.config.get("kb_fine"):
            return False
        scale.set_value(min(100, max(0, round(value / 25) * 25)))
        return True

    def on_kb_mode_changed(self, _combo):
        self.update_kb_visibility()
        self.debounce("kb", self.apply_keyboard, 0)

    def update_kb_visibility(self):
        if not self.has_kb:
            return
        mode_id = self.kb_mode.get_active_id()
        zones = mode_id == "zones"
        self.zone_box.set_visible(zones)
        self.effect_box.set_visible(not zones)
        if not zones:
            _, _, color, speed, direction = next(e for e in EFFECTS if str(e[0]) == mode_id)
            self.effect_color_row.set_visible(color)
            self.speed_row.set_visible(speed)
            self.direction_row.set_visible(direction)

    def on_same_color(self, _button):
        color = self.zone_buttons[0].get_rgba()
        for button in self.zone_buttons[1:]:
            button.set_rgba(color)
        self.debounce("kb", self.apply_keyboard, 0)

    def on_preset(self, _button, color):
        rgba = hex_to_rgba(color)
        self._updating = True
        for button in self.zone_buttons:
            button.set_rgba(rgba)
        self.effect_color.set_rgba(rgba)
        self._updating = False
        self.debounce("kb", self.apply_keyboard, 0)

    def capture_keyboard(self):
        brightness = int(self.brightness.get_value())
        mode_id = self.kb_mode.get_active_id()
        if mode_id == "zones":
            return {
                "mode": "zones",
                "zones": [rgba_to_hex(b.get_rgba()) for b in self.zone_buttons],
                "brightness": brightness,
            }
        return {
            "mode": int(mode_id),
            "speed": int(self.speed.get_value()),
            "direction": int(self.direction.get_active_id()),
            "color": rgba_to_hex(self.effect_color.get_rgba()),
            "brightness": brightness,
        }

    def apply_keyboard(self):
        self.apply(*keyboard_value(self.capture_keyboard()))

    # --- power ------------------------------------------------------------

    def build_power(self):
        box = page()

        box.pack_start(section("Power mode"), False, False, 0)
        modes, self.power_buttons = linked_radios(POWER_MODES, self.on_power_toggled)
        box.pack_start(modes, False, False, 0)
        box.pack_start(dim("Modes your laptop does not offer right now are greyed out."),
                       False, False, 0)

        self.fan_buttons = {}
        self.fan_scales = []
        if sense_path("fan_speed"):
            box.pack_start(section("Fans"), False, False, 0)
            fan_modes, self.fan_buttons = linked_radios(
                [("auto", "Auto"), ("max", "Max"), ("custom", "Custom")], self.on_fan_toggled,
            )
            box.pack_start(fan_modes, False, False, 0)
            for name in ("CPU fan", "GPU fan"):
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
                scale.set_size_request(220, -1)
                scale.set_value(50)
                scale.connect("value-changed", lambda *_: self.debounce("fan", self.apply_fan, 400))
                box.pack_start(row(f"{name} (%)", scale), False, False, 0)
                self.fan_scales.append(scale)

        self.sensor_labels = {}
        if self.hwmon:
            box.pack_start(section("Sensors"), False, False, 0)
            grid = Gtk.Grid(column_spacing=24, row_spacing=4)
            for i, name in enumerate(("CPU", "GPU")):
                grid.attach(Gtk.Label(label=name, xalign=0), 0, i, 1, 1)
                temp = Gtk.Label(xalign=1, width_chars=6)
                rpm = Gtk.Label(xalign=1, width_chars=10)
                rpm.get_style_context().add_class("dim-label")
                grid.attach(temp, 1, i, 1, 1)
                grid.attach(rpm, 2, i, 1, 1)
                self.sensor_labels[name] = (temp, rpm)
            box.pack_start(grid, False, False, 0)
        return box

    def on_power_toggled(self, button, key):
        if self._updating or not button.get_active():
            return
        try:
            write(PLATFORM_PROFILE, key)
        except PermissionError:
            self.set_power_with_pkexec(key)
            return
        except OSError as err:
            self.show_message(f"Could not change the power mode: {err.strerror}")
        self.refresh()

    def set_power_with_pkexec(self, key):
        """Fallback when the tmpfiles rule is not installed: ask polkit for a password."""
        try:
            proc = Gio.Subprocess.new(
                ["pkexec", GLib.find_program_in_path("tee") or "/usr/bin/tee", PLATFORM_PROFILE],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_SILENCE
                | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as err:
            self.show_message(f"Could not change the power mode: {err.message}")
            self.refresh()
            return

        def done(proc, result):
            _ok, _out, err = proc.communicate_utf8_finish(result)
            if proc.get_exit_status() != 0:
                self.show_message(f"Could not change the power mode: {(err or '').strip() or 'cancelled'}")
            self.refresh()

        proc.communicate_utf8_async(key, None, done)

    def on_fan_toggled(self, button, key):
        if not button.get_active():
            return
        for scale in self.fan_scales:
            scale.set_sensitive(key == "custom")
        self.debounce("fan", self.apply_fan, 0)

    def capture_fans(self):
        if self.fan_buttons["auto"].get_active():
            return "auto"
        if self.fan_buttons["max"].get_active():
            return "max"
        return [int(s.get_value()) for s in self.fan_scales]

    def apply_fan(self):
        self.apply(sense_path("fan_speed"), fan_value(self.capture_fans()))

    # --- battery ----------------------------------------------------------

    def build_battery(self):
        box = page()

        self.battery_label = Gtk.Label(xalign=0)
        box.pack_start(self.battery_label, False, False, 0)
        self.health_label = dim("")
        box.pack_start(self.health_label, False, False, 0)

        self.limiter = None
        path = sense_path("battery_limiter")
        if path:
            self.limiter = Gtk.Switch()
            self.limiter.connect("notify::active", self.on_switch, path)
            box.pack_start(
                row("Stop charging at 80%", self.limiter,
                    "Extends battery life when you mostly stay plugged in"),
                False, False, 0,
            )

        self.usb = None
        if sense_path("usb_charging"):
            self.usb = Gtk.ComboBoxText()
            self.usb.append("0", "Off")
            for level in (10, 20, 30):
                self.usb.append(str(level), f"Until battery is at {level}%")
            self.usb.set_active_id("0")
            self.usb.connect("changed", self.on_usb)
            box.pack_start(
                row("USB charging when off", self.usb, "Charge devices over USB while the laptop is off"),
                False, False, 0,
            )

        self.extra_switches = {}
        extras = [(n, t, h) for n, t, h in EXTRA_SWITCHES if writable(sense_path(n))]
        if extras:
            box.pack_start(section("Other"), False, False, 0)
        for name, title, hint in extras:
            switch = Gtk.Switch()
            switch.connect("notify::active", self.on_switch, sense_path(name))
            box.pack_start(row(title, switch, hint), False, False, 0)
            self.extra_switches[name] = switch
        return box

    def on_switch(self, switch, _param, path):
        if not self._updating:
            self.apply(path, "1" if switch.get_active() else "0")

    def on_usb(self, combo):
        if not self._updating:
            self.apply(sense_path("usb_charging"), combo.get_active_id())

    # --- profiles ---------------------------------------------------------

    def build_profiles(self):
        box = page()

        box.pack_start(section("Profiles"), False, False, 0)
        box.pack_start(dim("A profile stores the power mode, fan setting and keyboard lighting."),
                       False, False, 0)
        self.profile_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.profile_list.get_style_context().add_class("frame")
        empty = dim("No profiles yet")
        empty.set_margin_top(12)
        empty.set_margin_bottom(12)
        empty.set_xalign(0.5)
        empty.show()
        self.profile_list.set_placeholder(empty)
        box.pack_start(self.profile_list, False, False, 0)

        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.profile_name = Gtk.Entry(placeholder_text="Name for the current settings")
        self.profile_name.connect("activate", self.on_save_profile)
        save = Gtk.Button(label="Save")
        save.connect("clicked", self.on_save_profile)
        save_row.pack_start(self.profile_name, True, True, 0)
        save_row.pack_start(save, False, False, 0)
        box.pack_start(save_row, False, False, 0)

        box.pack_start(section("Automatic"), False, False, 0)
        self.auto_combos = {}
        for key, title, hint in (
            ("on_battery", "On battery", "Applied when you unplug the charger"),
            ("on_ac", "Plugged in", "Applied when you plug the charger in"),
        ):
            combo = Gtk.ComboBoxText()
            combo.connect("changed", self.on_auto_changed, key)
            box.pack_start(row(title, combo, hint), False, False, 0)
            self.auto_combos[key] = combo
        self.mode_key = Gtk.Switch()
        self.mode_key.connect("notify::active", self.on_mode_key)
        box.pack_start(
            row("NitroSense key notification", self.mode_key,
                "Show the new power mode, with a button that opens this panel"),
            False, False, 0,
        )
        box.pack_start(dim("These run in a small background service that starts with your session."),
                       False, False, 0)

        self.fill_profiles()
        return box

    def fill_profiles(self):
        self._updating = True
        for child in self.profile_list.get_children():
            self.profile_list.remove(child)
        names = sorted(self.config["profiles"], key=str.lower)
        for name in names:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            line.set_border_width(6)
            line.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            apply = Gtk.Button(label="Apply")
            apply.connect("clicked", self.on_apply_profile, name)
            delete = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
            delete.set_tooltip_text(f"Delete {name}")
            delete.connect("clicked", self.on_delete_profile, name)
            line.pack_start(apply, False, False, 0)
            line.pack_start(delete, False, False, 0)
            self.profile_list.add(line)
        self.profile_list.show_all()

        for key, combo in self.auto_combos.items():
            combo.remove_all()
            combo.append("off", "Do nothing")
            for name in names:
                combo.append(f"profile:{name}", name)
            chosen = self.config.get(key)
            combo.set_active_id(f"profile:{chosen}" if chosen in self.config["profiles"] else "off")
        self.mode_key.set_active(bool(self.config.get("mode_key")))
        self._updating = False

    def capture(self):
        profile = {}
        power = read(PLATFORM_PROFILE)
        if power:
            profile["power"] = power
        if self.fan_buttons:
            profile["fans"] = self.capture_fans()
        if self.has_kb:
            profile["keyboard"] = self.capture_keyboard()
        return profile

    def on_save_profile(self, _widget):
        name = self.profile_name.get_text().strip()
        if not name:
            self.show_message("Type a name for the profile first.", Gtk.MessageType.WARNING)
            return
        self.config["profiles"][name] = self.capture()
        self.save()
        self.profile_name.set_text("")
        self.fill_profiles()
        self.show_message(f"Saved “{name}”.", Gtk.MessageType.INFO)

    def on_apply_profile(self, _button, name):
        problems = apply_profile(self.config["profiles"][name], self.set_power_with_pkexec)
        self.load_state()
        self.refresh()
        if problems:
            self.show_message(f"Applied “{name}”, except: {'; '.join(problems)}.",
                              Gtk.MessageType.WARNING)
        else:
            self.show_message(f"Applied “{name}”.", Gtk.MessageType.INFO)

    def on_delete_profile(self, _button, name):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text=f"Delete the profile “{name}”?",
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.ACCEPT)
        confirmed = dialog.run() == Gtk.ResponseType.ACCEPT
        dialog.destroy()
        if not confirmed:
            return
        del self.config["profiles"][name]
        for key in self.auto_combos:
            if self.config.get(key) == name:
                self.config[key] = None
        self.save()
        self.fill_profiles()
        self.update_daemon()

    def on_auto_changed(self, combo, key):
        if self._updating:
            return
        active = combo.get_active_id() or "off"
        self.config[key] = active.removeprefix("profile:") if active != "off" else None
        self.save()
        self.update_daemon()

    def on_mode_key(self, switch, _param):
        if self._updating:
            return
        self.config["mode_key"] = switch.get_active()
        self.save()
        self.update_daemon()

    def save(self):
        try:
            save_config(self.config)
        except OSError as err:
            self.show_message(f"Could not save settings: {err.strerror}")

    def update_daemon(self):
        """Run the background service only while something needs it."""
        wanted = bool(self.config.get("on_battery") or self.config.get("on_ac")
                      or self.config.get("mode_key"))
        action = "enable" if wanted else "disable"
        try:
            proc = Gio.Subprocess.new(
                ["systemctl", "--user", action, "--now", DAEMON_UNIT],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as err:
            self.show_message(f"Could not {action} the background service: {err.message}")
            return

        def done(proc, result):
            _ok, _out, err = proc.communicate_utf8_finish(result)
            if proc.get_exit_status() != 0 and wanted:
                self.show_message(f"Could not start the background service: {(err or '').strip()}")

        proc.communicate_utf8_async(None, None, done)

    # --- reading state ----------------------------------------------------

    def load_state(self):
        self._updating = True
        try:
            if self.has_kb:
                self.load_keyboard()
            self.load_fans()
            if self.limiter:
                self.limiter.set_active(read(sense_path("battery_limiter")) == "1")
            if self.backlight_timeout:
                self.backlight_timeout.set_active(read(sense_path("backlight_timeout")) == "1")
            for name, switch in self.extra_switches.items():
                switch.set_active(read(sense_path(name)) == "1")
            usb = read(sense_path("usb_charging")) if self.usb else None
            if usb in ("0", "10", "20", "30"):
                self.usb.set_active_id(usb)
        finally:
            self._updating = False
        self.update_kb_visibility()

    def load_keyboard(self):
        four = read(FOUR_ZONE)
        per = read(PER_ZONE)
        try:
            if four:
                mode, speed, brightness, direction, r, g, b = (int(v) for v in four.split(","))
                self.kb_mode.set_active_id(str(mode) if mode != 0 else "zones")
                if mode != 0:
                    self.speed.set_value(max(speed, 1))
                    if direction in (1, 2):
                        self.direction.set_active_id(str(direction))
                self.effect_color.set_rgba(hex_to_rgba(f"{r:02x}{g:02x}{b:02x}"))
                self.brightness.set_value(brightness)
            if per and self.kb_mode.get_active_id() == "zones":
                *colors, brightness = per.split(",")
                for button, color in zip(self.zone_buttons, colors):
                    button.set_rgba(hex_to_rgba(color))
                self.brightness.set_value(int(brightness))
        except ValueError:
            pass  # unexpected driver output: keep what the widgets show

    def load_fans(self):
        if not self.fan_buttons:
            return
        fan = read(sense_path("fan_speed"))
        if fan in (None, "0,0"):
            self.fan_buttons["auto"].set_active(True)
        elif fan == "100,100":
            self.fan_buttons["max"].set_active(True)
        else:
            self.fan_buttons["custom"].set_active(True)
            for scale, value in zip(self.fan_scales, fan.split(",")):
                scale.set_value(int(value) if value.isdigit() and int(value) else 10)
        for scale in self.fan_scales:
            scale.set_sensitive(self.fan_buttons["custom"].get_active())

    def refresh(self):
        self._updating = True
        choices = (read(PLATFORM_CHOICES) or "").split()
        for key, button in self.power_buttons.items():
            button.set_sensitive(key in choices)
        active = read(PLATFORM_PROFILE)
        if active in self.power_buttons:
            self.power_buttons[active].set_active(True)
        # The Plasma widget may have switched Steps/Fine in the shared config
        fine = bool(load_config().get("kb_fine"))
        if self.has_kb and fine != bool(self.config.get("kb_fine")):
            self.config["kb_fine"] = fine
            self.kb_step_buttons["fine" if fine else "steps"].set_active(True)
            self.update_brightness_steps()
        self._updating = False

        # The embedded controller reports these, so reading them never
        # wakes a sleeping NVIDIA GPU.
        for i, name in enumerate(("CPU", "GPU"), start=1):
            if name in self.sensor_labels:
                temp, rpm = self.sensor_labels[name]
                temp.set_text(temperature(f"{self.hwmon}/temp{i}_input"))
                rpm.set_text(f"{read(f'{self.hwmon}/fan{i}_input') or '?'} RPM")

        if self.battery:
            capacity = read(f"{self.battery}/capacity")
            status = (read(f"{self.battery}/status") or "").lower()
            self.battery_label.set_markup(f"<big>Battery: {capacity}%</big>  {status}")
            self.health_label.set_text(battery_health(self.battery) or "")
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window() or NitroPanel(self)
        window.show_all()
        window.update_kb_visibility()
        window.present()


# --- background service -----------------------------------------------------


class Daemon:
    """Applies profiles on charger changes and reports NitroSense key presses."""

    def __init__(self):
        self.system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.notification_id = 0
        self.sent_ids = set()
        self.last_notify_ms = 0
        self.pending_apply = None
        self.on_battery = self.read_on_battery()

        self.system.signal_subscribe(
            "org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged",
            "/org/freedesktop/UPower", None, Gio.DBusSignalFlags.NONE, self.on_upower_changed,
        )
        self.session.signal_subscribe(
            "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked",
            "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, self.on_action,
        )
        self.session.signal_subscribe(
            "org.freedesktop.Notifications", "org.freedesktop.Notifications", "NotificationClosed",
            "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, self.on_closed,
        )
        self.schedule_apply()
        self.watch_mode_key()
        log(f"daemon started, {'on battery' if self.on_battery else 'plugged in'}")

    def read_on_battery(self):
        try:
            result = self.system.call_sync(
                "org.freedesktop.UPower", "/org/freedesktop/UPower",
                "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", ("org.freedesktop.UPower", "OnBattery")),
                GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 5000, None,
            )
            return bool(result.unpack()[0])
        except GLib.Error as err:
            log(f"cannot read the power source from UPower: {err.message}")
            return None

    def on_upower_changed(self, _conn, _sender, _path, _iface, _signal, params):
        _iface_name, changed, _invalidated = params.unpack()
        if "OnBattery" in changed and changed["OnBattery"] != self.on_battery:
            self.on_battery = changed["OnBattery"]
            self.schedule_apply()

    def schedule_apply(self):
        # The driver restores its own saved mode on charger events; apply after it.
        if self.pending_apply:
            GLib.source_remove(self.pending_apply)
        self.pending_apply = GLib.timeout_add(1500, self.apply_for_power_source)

    def apply_for_power_source(self):
        self.pending_apply = None
        if self.on_battery is None:
            return False
        config = load_config()
        name = config.get("on_battery" if self.on_battery else "on_ac")
        profile = config["profiles"].get(name) if name else None
        if profile:
            problems = apply_profile(profile)
            log(f"applied “{name}”" + (f", except: {'; '.join(problems)}" if problems else ""))
        return False

    def watch_mode_key(self):
        # The driver handles the key itself (it cycles the power mode) and only
        # leaves a line in the kernel log, so that log is the one signal we get.
        # No --grep here: combined with --follow it prints nothing.
        try:
            proc = Gio.Subprocess.new(
                ["journalctl", "--dmesg", "--follow", "--lines=0", "--output=cat"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error as err:
            log(f"cannot follow the kernel log, key notifications are off: {err.message}")
            return
        self.journal = proc
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_journal_line)

    def on_journal_line(self, stream, result):
        line, _length = stream.read_line_finish_utf8(result)
        if line is None:
            log("the kernel log watcher stopped, key notifications are off")
            return
        if "pressed turbo button" in line and load_config().get("mode_key"):
            GLib.timeout_add(300, self.notify_mode)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_journal_line)

    def notify_mode(self):
        mode = read(PLATFORM_PROFILE)
        label = POWER_LABELS.get(mode, mode or "unknown")
        # Update the popup while it is still on screen, so quick presses do not
        # stack up. Once it may have timed out, open a new one: KDE does not
        # report the timeout, and replacing a timed-out notification shows nothing.
        now = GLib.get_monotonic_time() // 1000
        if now - self.last_notify_ms > NOTIFY_TIMEOUT_MS - 500:
            self.notification_id = 0
        try:
            result = self.session.call_sync(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications", "Notify",
                GLib.Variant("(susssasa{sv}i)", (
                    "Nitro Panel", self.notification_id, "input-keyboard",
                    f"Power mode: {label}", "",
                    ["default", "Open Nitro Panel", "open", "Open Nitro Panel"],
                    {"desktop-entry": GLib.Variant("s", APP_ID),
                     "transient": GLib.Variant("b", True)},
                    NOTIFY_TIMEOUT_MS,
                )),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None,
            )
            self.notification_id = result.unpack()[0]
            self.sent_ids.add(self.notification_id)
            self.last_notify_ms = now
        except GLib.Error as err:
            log(f"cannot show a notification: {err.message}")
        return False

    def on_closed(self, _conn, _sender, _path, _iface, _signal, params):
        notification_id, _reason = params.unpack()
        if notification_id == self.notification_id:
            self.notification_id = 0

    def on_action(self, _conn, _sender, _path, _iface, _signal, params):
        notification_id, action = params.unpack()
        if notification_id in self.sent_ids and action in ("default", "open"):
            try:
                Gio.Subprocess.new([sys.executable, os.path.realpath(__file__)],
                                   Gio.SubprocessFlags.NONE)
            except GLib.Error as err:
                log(f"cannot open the panel: {err.message}")


def main():
    args = sys.argv[1:]
    if "--daemon" in args:
        Daemon()
        GLib.MainLoop().run()
        return 0
    return App().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
