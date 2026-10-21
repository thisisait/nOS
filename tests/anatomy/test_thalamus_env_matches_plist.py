"""Anatomy gate — the Linux thalamus env carries what the macOS plist carries.

THE SYMPTOM (2026-10-21, spark1). ``iris_plan: hybrid`` with ``install_cortex``
rendered NOS_IRIS_PLAN=hybrid into thalamus.env but neither NOS_CORTEX_URL nor
NOS_IRIS_INTENTS: the env only wired the organ for ``cortex``, so hybrid on
Linux silently planned nothing, and iris-bench --plan hybrid refuses an env
without NOS_IRIS_INTENTS. NOS_CORTEX_CATALOGUE and NOS_DECIDER_EXES were
missing too. The two templates are one service on two service managers.

THE CHECK. The variable names each template can set are the same set, except
the names that exist only because of the service manager (below).

CEILING. Compares names, not the conditions around them; the effect is the
running thalamus's environment.
"""

import re
from pathlib import Path

T = Path(__file__).resolve().parents[2] / "roles" / "pazny.thalamus" / "templates"
# systemd hands thalamus a shared socket and relay host; launchd sockets live in the plist's own keys.
LINUX_ONLY = {"THALAMUS_RELAY_HOST", "THALAMUS_SOCKET", "THALAMUS_SOCKET_SHARED"}


def _plist() -> set[str]:
    return set(re.findall(r"<key>([A-Z][A-Z0-9_]+)</key>", (T / "thalamus.plist.j2").read_text(encoding="utf-8")))


def _env() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", (T / "thalamus.env.j2").read_text(encoding="utf-8"), re.M))


def test_linux_env_sets_every_plist_variable():
    missing = sorted(_plist() - _env())
    assert not missing, f"thalamus.env.j2 never sets {missing}, which thalamus.plist.j2 does"


def test_linux_only_names_are_the_known_ones():
    extra = sorted(_env() - _plist() - LINUX_ONLY)
    assert not extra, f"thalamus.env.j2 sets {extra}, which the plist does not: add them there or to LINUX_ONLY"


def test_hybrid_wires_the_organ_on_linux():
    env = (T / "thalamus.env.j2").read_text(encoding="utf-8")
    assert re.search(r"iris_plan[^%]*in \[\s*'cortex',\s*'hybrid'\s*\]", env), \
        "thalamus.env.j2 wires NOS_CORTEX_URL only for iris_plan cortex, so hybrid plans nothing"
