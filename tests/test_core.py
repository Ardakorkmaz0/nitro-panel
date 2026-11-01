"""Profiles, sysfs values and config handling."""

import nitro_panel as np


def test_keyboard_value_zones():
    path, value = np.keyboard_value(
        {"mode": "zones", "zones": ["ff0000", "00ff00", "0000ff", "ffffff"], "brightness": 40},
    )
    assert path == np.PER_ZONE
    assert value == "ff0000,00ff00,0000ff,ffffff,40"


def test_keyboard_value_effect():
    path, value = np.keyboard_value(
        {"mode": 3, "speed": 4, "direction": 1, "color": "00ff80", "brightness": 60},
    )
    assert path == np.FOUR_ZONE
    assert value == "3,4,60,1,0,255,128"


def test_fan_value():
    assert np.fan_value("auto") == "0,0"
    assert np.fan_value("max") == "100,100"
    assert np.fan_value([40, 60]) == "40,60"
    # 100,100 means max mode to the driver, so custom stays just below it
    assert np.fan_value([100, 100]) == "100,95"


def test_apply_profile_writes_every_part(fake_sys):
    problems = np.apply_profile({
        "power": "quiet",
        "fans": [50, 70],
        "keyboard": {"mode": "zones", "zones": ["ffffff"] * 4, "brightness": 30},
    })
    assert problems == []
    assert fake_sys.read(fake_sys.profile) == "quiet"
    assert fake_sys.read(fake_sys.fan) == "50,70"
    assert fake_sys.read(fake_sys.per_zone) == "ffffff,ffffff,ffffff,ffffff,30"


def test_apply_profile_reports_unavailable_mode(fake_sys):
    fake_sys.choices.write_text("low-power balanced\n")  # on battery: no Turbo
    problems = np.apply_profile({"power": "performance", "fans": "auto"})
    assert problems == ["Turbo mode is not available right now"]
    assert fake_sys.read(fake_sys.profile) == "balanced"
    assert fake_sys.read(fake_sys.fan) == "0,0"  # the rest still applies


def test_apply_profile_reports_damaged_data(fake_sys):
    assert np.apply_profile({"keyboard": {"mode": "zones"}}) == ["the profile data is damaged"]


def test_keyboard_state_zones_and_effect(fake_sys):
    assert np.keyboard_state() == {
        "mode": "zones", "zones": ["ff0000", "00ff00", "0000ff", "ffffff"], "brightness": 100,
    }
    fake_sys.four_zone.write_text("3,0,70,0,0,0,0\n")
    state = np.keyboard_state()
    assert state["mode"] == 3
    assert state["speed"] == 1        # the driver may report 0; the UI needs 1-9
    assert state["direction"] == 2    # wave needs a direction
    assert state["brightness"] == 70


def test_keyboard_state_without_keyboard(fake_sys):
    fake_sys.four_zone.unlink()
    assert np.keyboard_state() is None


def test_battery_health(fake_sys):
    assert np.battery_health(str(fake_sys.battery)) == (
        "Health: 71% of original capacity (4.19 of 5.88 Ah)"
    )


def test_config_defaults_and_round_trip(fake_sys):
    config = np.load_config()
    assert sorted(config["profiles"]) == ["Battery saver", "Gaming", "Quiet"]
    assert config["kb_fine"] is False

    config["on_battery"] = "Quiet"
    del config["profiles"]["Gaming"]
    np.save_config(config)

    again = np.load_config()
    assert again["on_battery"] == "Quiet"
    assert "Gaming" not in again["profiles"]


def test_sense_path_only_for_existing_files(fake_sys):
    assert np.sense_path("fan_speed") == str(fake_sys.fan)
    assert np.sense_path("lcd_override") is None
