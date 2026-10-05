"""Gate: the directory nginx.conf caches into is created before `nginx -t`.

macOS-15 CI 2026-10-05: proxy_cache_path pointed at <prefix>/var/cache/nginx,
a clean runner had no var/cache, and `nginx -t` failed on mkdir. Both sides are
rendered for macOS and Linux and compared.
"""
import re
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("family,prefix", [("Darwin", "/opt/homebrew"), ("Debian", "/usr/local")])
def test_proxy_cache_path_is_a_created_dir(family, prefix):
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    ctx = {"ansible_os_family": family, "homebrew_prefix": prefix,
           "nginx_etc_dir": "/e", "nginx_log_dir": "/l"}
    conf = env.from_string((REPO / "templates/nginx/nginx.conf").read_text()).render(**ctx)
    cache = re.search(r"proxy_cache_path\s+(\S+)", conf).group(1)
    task = next(t for t in yaml.safe_load((REPO / "tasks/nginx.yml").read_text())
                if t.get("name") == "Ensure nginx sites directories exist")
    made = [env.from_string(i).render(**ctx) for i in task["loop"]]
    assert cache in made, f"{cache} is not created before nginx -t: {made}"
