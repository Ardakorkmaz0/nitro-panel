"""Install layout, version handling and release notes."""

import json
import re
import subprocess
import sys
from pathlib import Path

import nitro_panel as np

ROOT = Path(__file__).resolve().parent.parent


def test_version_lives_in_one_place():
    assert re.fullmatch(r"\d+\.\d+\.\d+", np.__version__)
    metadata = json.loads((ROOT / "plasmoid" / "metadata.json").read_text())
    assert "Version" not in metadata["KPlugin"], "the widget version comes from nitro_panel.py"


def test_make_install(tmp_path):
    subprocess.run(["make", "-s", "install", f"DESTDIR={tmp_path}", "PREFIX=/usr"],
                   cwd=ROOT, check=True)
    expected = [
        "usr/bin/nitro-panel",
        "usr/lib/systemd/user/nitro-panel-daemon.service",
        "usr/lib/tmpfiles.d/nitro-panel.conf",
        "usr/share/applications/io.github.ardakorkmaz0.NitroPanel.desktop",
        "usr/share/plasma/plasmoids/io.github.ardakorkmaz0.nitropanel/contents/ui/main.qml",
        "usr/share/plasma/plasmoids/io.github.ardakorkmaz0.nitropanel/metadata.json",
    ]
    installed = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert installed == expected

    widget = json.loads((tmp_path / expected[-1]).read_text())
    assert widget["KPlugin"]["Version"] == np.__version__
    unit = (tmp_path / expected[1]).read_text()
    assert "ExecStart=/usr/bin/nitro-panel --daemon" in unit


def test_tmpfiles_rule_has_no_globs():
    """tmpfiles refuses to glob through the acer-wmi symlink and skips the line silently."""
    for line in (ROOT / "data" / "nitro-panel.tmpfiles.conf").read_text().splitlines():
        if line and not line.startswith("#"):
            path = line.split()[1]
            assert not any(c in path for c in "*?["), f"glob in tmpfiles rule: {path}"


def test_changelog_has_the_current_version():
    """A release is published from this entry, so it has to exist."""
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "release_notes.py"), np.__version__],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip()
