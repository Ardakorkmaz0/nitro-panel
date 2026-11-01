"""The background service's charger logic, without D-Bus."""

import nitro_panel as np


def charger_daemon(on_battery):
    daemon = np.Daemon.__new__(np.Daemon)  # skip __init__, which connects to D-Bus
    daemon.pending_apply = None
    daemon.on_battery = on_battery
    return daemon


def test_unplugging_applies_the_battery_profile(fake_sys):
    config = np.load_config()
    config["on_battery"] = "Battery saver"
    config["on_ac"] = "Gaming"
    np.save_config(config)

    charger_daemon(on_battery=True).apply_for_power_source()
    assert fake_sys.read(fake_sys.profile) == "low-power"
    assert fake_sys.read(fake_sys.per_zone).endswith(",0")

    charger_daemon(on_battery=False).apply_for_power_source()
    assert fake_sys.read(fake_sys.profile) == "performance"
    assert fake_sys.read(fake_sys.per_zone) == "ff0000,ff0000,ff0000,ff0000,100"


def test_do_nothing_leaves_the_hardware_alone(fake_sys):
    charger_daemon(on_battery=True).apply_for_power_source()
    assert fake_sys.read(fake_sys.profile) == "balanced"


def test_unknown_power_source_is_ignored(fake_sys):
    config = np.load_config()
    config["on_battery"] = "Quiet"
    np.save_config(config)
    charger_daemon(on_battery=None).apply_for_power_source()
    assert fake_sys.read(fake_sys.profile) == "balanced"
