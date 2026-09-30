"""Gate: Open WebUI's first boot (embedding-model download) fits start_period.

A blank on 2026-09-30 failed the STRICT health wait: the download took ~2 min,
start_period was 60s, so the container went unhealthy while still working.
"""
import re
from pathlib import Path

TPL = Path(__file__).resolve().parents[2] / "roles/pazny.open_webui/templates/compose.yml.j2"


def test_start_period_covers_the_model_download():
    m = re.search(r"^\s*start_period:\s*(\d+)s", TPL.read_text(), re.M)
    assert m and int(m.group(1)) >= 240, m and m.group(0)
