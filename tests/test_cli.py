"""The command line options the Plasma widget relies on."""

import json
import os
import subprocess
import sys
from pathlib import Path

import nitro_panel as np

SCRIPT = Path(__file__).resolve().parent.parent / "nitro_panel.py"


def run(capsys, *args):
    code = np.cli(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_status_json(fake_sys, capsys):
    code, out, _ = run(capsys, "--status")
    assert code == 0
    status = json.loads(out)
    assert status["available"] is True
    assert status["mode"] == "balanced"
    assert [m["label"] for m in status["modes"]] == ["Eco", "Quiet", "Balanced", "Performance", "Turbo"]
    assert all(m["available"] for m in status["modes"])
    assert status["keyboard_brightness"] == 100
    assert status["keyboard_fine"] is False
    assert status["battery_limit"] is False
    assert status["sensors"] == {"cpu_temp": 51, "gpu_temp": 47, "cpu_fan": 2100, "gpu_fan": 1900}
    assert status["profiles"] == ["Battery saver", "Gaming", "Quiet"]


def test_mode_accepts_labels(fake_sys, capsys):
    assert run(capsys, "--mode", "Turbo")[0] == 0
    assert fake_sys.read(fake_sys.profile) == "performance"
    assert run(capsys, "--mode", "low-power")[0] == 0
    assert fake_sys.read(fake_sys.profile) == "low-power"


def test_mode_rejects_unavailable(fake_sys, capsys):
    fake_sys.choices.write_text("low-power balanced\n")
    code, _, err = run(capsys, "--mode", "turbo")
    assert code == 1
    assert "Turbo mode is not available" in err
    assert fake_sys.read(fake_sys.profile) == "balanced"


def test_kb_brightness_keeps_colors(fake_sys, capsys):
    assert run(capsys, "--kb-brightness", "25")[0] == 0
    assert fake_sys.read(fake_sys.per_zone) == "ff0000,00ff00,0000ff,ffffff,25"


def test_kb_brightness_keeps_effect(fake_sys, capsys):
    fake_sys.four_zone.write_text("3,5,100,2,0,0,0\n")
    assert run(capsys, "--kb-brightness", "50")[0] == 0
    assert fake_sys.read(fake_sys.four_zone) == "3,5,50,2,0,0,0"


def test_kb_brightness_rejects_bad_values(fake_sys, capsys):
    for value in ("150", "-1", "abc"):
        code, _, err = run(capsys, "--kb-brightness", value)
        assert code == 1
        assert "0 to 100" in err


def test_profile(fake_sys, capsys):
    assert run(capsys, "--profile", "Quiet")[0] == 0
    assert fake_sys.read(fake_sys.profile) == "quiet"
    code, _, err = run(capsys, "--profile", "Nope")
    assert code == 1
    assert "no profile called 'Nope'" in err


def test_battery_limit(fake_sys, capsys):
    assert run(capsys, "--battery-limit", "on")[0] == 0
    assert fake_sys.read(fake_sys.limiter) == "1"
    assert run(capsys, "--battery-limit", "maybe")[0] == 1


def test_kb_fine_is_saved(fake_sys, capsys):
    assert run(capsys, "--kb-fine", "on")[0] == 0
    assert np.load_config()["kb_fine"] is True
    assert json.loads(run(capsys, "--status")[1])["keyboard_fine"] is True


def test_missing_value(fake_sys, capsys):
    code, _, err = run(capsys, "--mode")
    assert code == 1
    assert "needs a value" in err


def test_command_line_never_loads_gtk(tmp_path):
    """The widget polls --status every few seconds; it has to stay quick."""
    blocker = tmp_path / "gi"
    blocker.mkdir()
    (blocker / "__init__.py").write_text("raise ImportError('the command line must not import gi')\n")
    env = dict(os.environ, PYTHONPATH=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "config"))
    for args in (["--version"], ["--help"], ["--status"]):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("{")
