"""A fake Linuwu-Sense sysfs tree, so the tests run without Acer hardware."""

from types import SimpleNamespace

import pytest

import nitro_panel


@pytest.fixture
def fake_sys(tmp_path, monkeypatch):
    base = tmp_path / "acer-wmi"
    kb = base / "four_zoned_kb"
    sense = base / "nitro_sense"
    acpi = tmp_path / "acpi"
    hwmon = tmp_path / "hwmon"
    battery = tmp_path / "BAT1"
    for folder in (kb, sense, acpi, hwmon, battery):
        folder.mkdir(parents=True)

    files = {
        kb / "four_zone_mode": "0,0,100,0,255,0,0",
        kb / "per_zone_mode": "ff0000,00ff00,0000ff,ffffff,100",
        sense / "fan_speed": "0,0",
        sense / "battery_limiter": "0",
        sense / "usb_charging": "0",
        sense / "backlight_timeout": "1",
        acpi / "platform_profile": "balanced",
        acpi / "platform_profile_choices": "low-power quiet balanced balanced-performance performance",
        hwmon / "name": "acer",
        hwmon / "temp1_input": "51000",
        hwmon / "temp2_input": "47000",
        hwmon / "fan1_input": "2100",
        hwmon / "fan2_input": "1900",
        battery / "capacity": "80",
        battery / "status": "Charging",
        battery / "charge_full": "4191000",
        battery / "charge_full_design": "5884000",
    }
    for path, value in files.items():
        path.write_text(value + "\n")

    monkeypatch.setattr(nitro_panel, "BASE", str(base))
    monkeypatch.setattr(nitro_panel, "FOUR_ZONE", str(kb / "four_zone_mode"))
    monkeypatch.setattr(nitro_panel, "PER_ZONE", str(kb / "per_zone_mode"))
    monkeypatch.setattr(nitro_panel, "PLATFORM_PROFILE", str(acpi / "platform_profile"))
    monkeypatch.setattr(nitro_panel, "PLATFORM_CHOICES", str(acpi / "platform_profile_choices"))
    monkeypatch.setattr(nitro_panel, "CONFIG_FILE", str(tmp_path / "config" / "config.json"))
    monkeypatch.setattr(nitro_panel, "find_hwmon", lambda name: str(hwmon))
    monkeypatch.setattr(nitro_panel, "find_battery", lambda: str(battery))

    def read(path):
        return path.read_text().strip()

    return SimpleNamespace(
        base=base, kb=kb, sense=sense, acpi=acpi, hwmon=hwmon, battery=battery, read=read,
        four_zone=kb / "four_zone_mode", per_zone=kb / "per_zone_mode",
        profile=acpi / "platform_profile", choices=acpi / "platform_profile_choices",
        fan=sense / "fan_speed", limiter=sense / "battery_limiter",
        timeout=sense / "backlight_timeout",
    )
