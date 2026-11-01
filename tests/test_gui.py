"""Build the panel window against the fake hardware and use a few controls.

Needs a display; CI runs the tests under xvfb-run.
"""

import pytest

import nitro_panel as np
from nitro_panel import Gdk, Gtk

pytestmark = pytest.mark.skipif(Gdk.Display.get_default() is None, reason="no display")


@pytest.fixture(scope="module")
def app():
    # Registered once: D-Bus refuses a second object at the same path
    app = Gtk.Application(application_id="io.github.ardakorkmaz0.NitroPanelTest")
    app.register(None)
    return app


@pytest.fixture
def window(app, fake_sys):
    win = np.NitroPanel(app)
    writes = []
    win.apply = lambda path, value: writes.append((path, value))
    win.writes = writes
    yield win
    win.destroy()


def test_all_tabs_are_built(window):
    stack = next(c for c in window.get_child().get_children() if isinstance(c, Gtk.Stack))
    names = [stack.child_get_property(c, "name") for c in stack.get_children()]
    assert names == ["keyboard", "power", "battery", "profiles"]


def test_state_is_loaded_from_the_driver(window):
    assert window.kb_mode.get_active_id() == "zones"
    assert window.capture_keyboard()["zones"] == ["ff0000", "00ff00", "0000ff", "ffffff"]
    assert window.power_buttons["balanced"].get_active()
    assert window.fan_buttons["auto"].get_active()
    assert "71%" in window.health_label.get_text()


def test_idle_timeout_switch(window, fake_sys):
    assert window.backlight_timeout is not None
    assert window.backlight_timeout.get_active()
    window.backlight_timeout.set_active(False)
    assert (str(fake_sys.timeout), "0") in window.writes


def test_brightness_snaps_to_steps_unless_fine(window):
    window.brightness.emit("change-value", Gtk.ScrollType.JUMP, 62)
    assert window.brightness.get_value() == 50
    window.kb_step_buttons["fine"].set_active(True)
    window.brightness.emit("change-value", Gtk.ScrollType.JUMP, 62)
    assert window.brightness.get_value() == 62


def test_capture_matches_what_profiles_store(window):
    profile = window.capture()
    assert profile["power"] == "balanced"
    assert profile["fans"] == "auto"
    assert profile["keyboard"]["mode"] == "zones"
