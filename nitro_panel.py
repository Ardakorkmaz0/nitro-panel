#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Nitro Panel: a small GTK control panel for Acer Nitro and Predator laptops.

It talks to the Linuwu-Sense kernel module through sysfs. Keyboard, fan and
battery files need the user to be in the linuwu_sense group. The power mode
file is made group-writable by the bundled tmpfiles rule; without it, the
panel falls back to pkexec.
"""

import glob
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

__version__ = "0.1.0"

APP_ID = "io.github.ardakorkmaz0.NitroPanel"

BASE = "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi"
FOUR_ZONE = f"{BASE}/four_zoned_kb/four_zone_mode"
PER_ZONE = f"{BASE}/four_zoned_kb/per_zone_mode"
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
PLATFORM_CHOICES = "/sys/firmware/acpi/platform_profile_choices"

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
PROFILES = [
    ("low-power", "Eco"),
    ("quiet", "Quiet"),
    ("balanced", "Balanced"),
    ("balanced-performance", "Performance"),
    ("performance", "Turbo"),
]

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


def read(path):
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


def rgba_to_hex(rgba):
    return "".join(f"{round(c * 255):02x}" for c in (rgba.red, rgba.green, rgba.blue))


def hex_to_rgba(value):
    rgba = Gdk.RGBA()
    rgba.parse(f"#{value}")
    return rgba


def find_sense_dir():
    for name in ("nitro_sense", "predator_sense"):
        path = f"{BASE}/{name}"
        if os.path.isdir(path):
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
        self.sense = find_sense_dir()
        self.hwmon = find_hwmon("acer")
        self.battery = find_battery()
        self.has_kb = os.path.exists(PER_ZONE)
        self.backlight_timeout = None

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        if self.has_kb:
            stack.add_titled(self.build_keyboard(), "keyboard", "Keyboard")
        stack.add_titled(self.build_power(), "power", "Power")
        stack.add_titled(self.build_battery(), "battery", "Battery")

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
        elif self.sense_path("fan_speed") and not writable(self.sense_path("fan_speed")):
            self.show_message(
                "No write access yet. Run: sudo usermod -aG linuwu_sense $USER, "
                "then log out and back in.",
                Gtk.MessageType.WARNING,
            )

        self.load_state()
        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    # --- helpers ----------------------------------------------------------

    def sense_path(self, name):
        if not self.sense:
            return None
        path = f"{self.sense}/{name}"
        return path if os.path.exists(path) else None

    def show_message(self, text, kind=Gtk.MessageType.ERROR):
        self.info.set_message_type(kind)
        self.info_label.set_text(text)
        self.info.set_revealed(True)

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

        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.brightness.set_size_request(220, -1)
        self.brightness.set_value(100)
        self.brightness.connect("value-changed", lambda *_: self.debounce("kb", self.apply_keyboard))
        box.pack_start(row("Brightness", self.brightness, "0 turns the light off"), False, False, 0)

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        for name, color in PRESETS:
            button = Gtk.Button(label=name)
            button.connect("clicked", self.on_preset, color)
            presets.pack_start(button, True, True, 0)
        box.pack_start(section("Quick colors"), False, False, 0)
        box.pack_start(presets, False, False, 0)

        path = self.sense_path("backlight_timeout")
        if writable(path):
            self.backlight_timeout = Gtk.Switch()
            self.backlight_timeout.connect("notify::active", self.on_switch, path)
            box.pack_start(section("Other"), False, False, 0)
            box.pack_start(
                row("Turn off when idle", self.backlight_timeout,
                    "Switch the keyboard light off after a short idle period"),
                False, False, 0,
            )
        return box

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

    def apply_keyboard(self):
        brightness = int(self.brightness.get_value())
        mode_id = self.kb_mode.get_active_id()
        if mode_id == "zones":
            colors = ",".join(rgba_to_hex(b.get_rgba()) for b in self.zone_buttons)
            self.apply(PER_ZONE, f"{colors},{brightness}")
            return
        c = self.effect_color.get_rgba()
        r, g, b = (round(v * 255) for v in (c.red, c.green, c.blue))
        speed = int(self.speed.get_value())
        direction = self.direction.get_active_id()
        self.apply(FOUR_ZONE, f"{mode_id},{speed},{brightness},{direction},{r},{g},{b}")

    # --- power ------------------------------------------------------------

    def build_power(self):
        box = page()

        box.pack_start(section("Power mode"), False, False, 0)
        profiles, self.profile_buttons = linked_radios(PROFILES, self.on_profile_toggled)
        box.pack_start(profiles, False, False, 0)
        box.pack_start(dim("Modes your laptop does not offer right now are greyed out."),
                       False, False, 0)

        self.fan_buttons = {}
        self.fan_scales = []
        if self.sense_path("fan_speed"):
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

        self.rpm_label = dim("")
        box.pack_start(self.rpm_label, False, False, 0)
        return box

    def on_profile_toggled(self, button, key):
        if self._updating or not button.get_active():
            return
        try:
            write(PLATFORM_PROFILE, key)
        except PermissionError:
            self.set_profile_with_pkexec(key)
            return
        except OSError as err:
            self.show_message(f"Could not change the power mode: {err.strerror}")
        self.refresh()

    def set_profile_with_pkexec(self, key):
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

    def apply_fan(self):
        if self.fan_buttons["auto"].get_active():
            value = "0,0"
        elif self.fan_buttons["max"].get_active():
            value = "100,100"
        else:
            cpu, gpu = (int(s.get_value()) for s in self.fan_scales)
            # The driver treats 100,100 as max mode; stay in custom mode
            if cpu == 100 and gpu == 100:
                gpu = 95
            value = f"{cpu},{gpu}"
        self.apply(self.sense_path("fan_speed"), value)

    # --- battery ----------------------------------------------------------

    def build_battery(self):
        box = page()

        self.battery_label = Gtk.Label(xalign=0)
        box.pack_start(self.battery_label, False, False, 0)

        self.limiter = None
        path = self.sense_path("battery_limiter")
        if path:
            self.limiter = Gtk.Switch()
            self.limiter.connect("notify::active", self.on_switch, path)
            box.pack_start(
                row("Stop charging at 80%", self.limiter,
                    "Extends battery life when you mostly stay plugged in"),
                False, False, 0,
            )

        self.usb = None
        if self.sense_path("usb_charging"):
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
        extras = [(n, t, h) for n, t, h in EXTRA_SWITCHES if writable(self.sense_path(n))]
        if extras:
            box.pack_start(section("Other"), False, False, 0)
        for name, title, hint in extras:
            switch = Gtk.Switch()
            switch.connect("notify::active", self.on_switch, self.sense_path(name))
            box.pack_start(row(title, switch, hint), False, False, 0)
            self.extra_switches[name] = switch
        return box

    def on_switch(self, switch, _param, path):
        if not self._updating:
            self.apply(path, "1" if switch.get_active() else "0")

    def on_usb(self, combo):
        if not self._updating:
            self.apply(self.sense_path("usb_charging"), combo.get_active_id())

    # --- reading state ----------------------------------------------------

    def load_state(self):
        self._updating = True
        try:
            if self.has_kb:
                self.load_keyboard()
            self.load_fans()
            if self.limiter:
                self.limiter.set_active(read(self.sense_path("battery_limiter")) == "1")
            if self.backlight_timeout:
                self.backlight_timeout.set_active(read(self.sense_path("backlight_timeout")) == "1")
            for name, switch in self.extra_switches.items():
                switch.set_active(read(self.sense_path(name)) == "1")
            usb = read(self.sense_path("usb_charging")) if self.usb else None
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
                if mode != 0:
                    self.kb_mode.set_active_id(str(mode))
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
            pass  # unexpected driver output: keep the defaults

    def load_fans(self):
        if not self.fan_buttons:
            return
        fan = read(self.sense_path("fan_speed"))
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
        for key, button in self.profile_buttons.items():
            button.set_sensitive(key in choices)
        active = read(PLATFORM_PROFILE)
        if active in self.profile_buttons:
            self.profile_buttons[active].set_active(True)
        self._updating = False

        if self.hwmon:
            fans = [read(f"{self.hwmon}/fan{i}_input") for i in (1, 2)]
            self.rpm_label.set_text(f"Current speed: CPU {fans[0] or '?'} RPM · GPU {fans[1] or '?'} RPM")

        if self.battery:
            capacity = read(f"{self.battery}/capacity")
            status = (read(f"{self.battery}/status") or "").lower()
            self.battery_label.set_markup(f"<big>Battery: {capacity}%</big>  {status}")
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window() or NitroPanel(self)
        window.show_all()
        window.update_kb_visibility()
        window.present()


def main():
    if "--version" in sys.argv[1:]:
        print(f"nitro-panel {__version__}")
        return 0
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
