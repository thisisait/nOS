"""A Docker image pin lives in default.config.yml, never in config.d/.

The upgrade path writes one config file: MigrationWriteTool CONFIG_BASENAME and
tools/migration-pr.sh CONFIG_FILE are both default.config.yml. A pin moved into a
config.d/ slice (70-geo did it for qgis, martin, geolibre, tileserver-gl) cannot be
bumped by an agent, or gets a second declaration that test_a_pin_is_declared_once
refuses. Widening that write allowlist is the operator's call, not a split's.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from test_a_pin_is_declared_once import KEY

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def _image_refs() -> str:
    """Every role line that puts a variable into an image reference."""
    lines = []
    for p in REPO.glob("roles/pazny.*/**/*"):
        if p.is_file() and p.suffix in {".j2", ".yml", ".yaml"}:
            lines += [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                      if "image" in l or re.search(r"[\w./-]:\{\{", l)]
    return "\n".join(lines)


def test_no_image_pin_lives_in_config_d():
    refs = _image_refs()
    assert "{{ martin_image }}" in refs, "positive control: role image refs not read"
    stray = []
    for p in ni.default_layers()[:-1]:   # every layer but the remainder
        for m in re.finditer(rf"^({KEY}):", p.read_text(encoding="utf-8"), re.M):
            if re.search(rf"\{{\{{\s*{m.group(1)}\s*\}}\}}", refs):
                stray.append(f"{p.relative_to(REPO)}: {m.group(1)}")
    assert not stray, ("image pins outside the file the upgrade path can write; "
                       "move them to default.config.yml:\n  " + "\n  ".join(stray))
