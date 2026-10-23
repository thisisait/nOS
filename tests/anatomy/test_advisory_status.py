"""tools/advisory-status.py reads every pin against its upstream's advisories.

WHY. The estate ran FrankenPHP 1.13.1 for two days after php/frankenphp
published GHSA-6q3j-62j9-f9hh (high), GHSA-ccgp-ch9h-533f, GHSA-fq24-r53r-xcx3
and GHSA-4gfw-9v29-gp9h, all fixed in 1.13.2, and nothing noticed: the nightly
scan never reads a pin. This pins the four things that would have caught it:

  * the matcher — exact ranges (introduced <= v < fixed, last_affected
    inclusive), prereleases, and image tags such as "16.15-alpine";
  * receptor coverage — a pin with no row in state/genome/advisory-receptors.yml
    fails here, naming the pin, so a new pin cannot go unheard;
  * a source that cannot be read is UNKNOWN on its own, never "no findings";
  * the FrankenPHP case itself: 1.13.1 -> the four GHSAs, 1.13.3 -> none.

HOW. Offline. The reader's one fetch seam is replaced by a stub that serves
tests/fixtures/advisory/ or raises. The FrankenPHP fixture is the shape of
api.github.com/repos/php/frankenphp/security-advisories, transcribed
2026-10-23 (ids, severities, vulnerable_version_range, patched_versions), not
a byte capture. The OSV case is synthetic and says so.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "advisory-status.py"
FIXTURES = REPO / "tests" / "fixtures" / "advisory"
FRANKENPHP = "https://api.github.com/repos/php/frankenphp/security-advisories"
FOUR = {"GHSA-6q3j-62j9-f9hh", "GHSA-ccgp-ch9h-533f", "GHSA-fq24-r53r-xcx3", "GHSA-4gfw-9v29-gp9h"}


def _load():
    spec = importlib.util.spec_from_file_location("advisory_status", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def adv():
    assert TOOL.is_file(), "tools/advisory-status.py does not exist"
    return _load()


def _refuse(url, body=None):
    raise OSError(f"offline: {url}")


# --- the matcher -------------------------------------------------------------

@pytest.mark.parametrize("v, ev, want", [
    ("1.5.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, True),           # in range
    ("0.9.9", {"introduced": "1.0.0", "fixed": "2.0.0"}, False),          # below introduced
    ("1.0.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, True),           # introduced is inclusive
    ("2.0.0", {"introduced": "1.0.0", "fixed": "2.0.0"}, False),          # at fixed
    ("1.13.1", {"introduced": "0", "last_affected": "1.13.1"}, True),     # last_affected inclusive
    ("1.13.2", {"introduced": "0", "last_affected": "1.13.1"}, False),
    ("2.0.0-rc.1", {"introduced": "1.0.0", "fixed": "2.0.0"}, True),      # prerelease sorts before release
    ("2.0.0-rc.1", {"introduced": "2.0.0"}, False),
    ("6.0.0-dev", {"introduced": "5.0.0", "fixed": "6.0.0"}, True),
    ("1.0.0-rc.1", {"introduced": "1.0.0-beta.2", "fixed": "1.0.0"}, True),
    ("16.15-alpine", {"introduced": "16.0", "fixed": "16.16"}, True),     # image tag: variant, not prerelease
    ("16.15-alpine", {"introduced": "16.0", "fixed": "16.15"}, False),
    ("v1.89.0-alpine", {"introduced": "1.0.0", "fixed": "1.89.1"}, True),
    ("1.30.4-alpine@sha256:97d4", {"introduced": "1.30.0", "fixed": "1.30.5"}, True),  # digest dropped
    ("18.11.12-ce.0", {"introduced": "18.11.0", "fixed": "18.11.12"}, False),
])
def test_the_matcher_is_exact(adv, v, ev, want):
    assert adv.in_range(v, **ev) is want, f"{v} vs {ev}"


@pytest.mark.parametrize("v, rng, want", [
    ("1.13.1", "<= 1.13.1", True),
    ("1.13.2", "<= 1.13.1", False),
    ("1.2.2", ">= 1.0, < 1.2.3", True),
    ("1.2.3", ">= 1.0, < 1.2.3", False),
    ("0.9", ">= 1.0, < 1.2.3", False),
    ("3.0.0", "= 3.0.0", True),
    ("3.0.1", "> 3.0.0, < 3.1", True),
    ("3.0.0", "> 3.0.0, < 3.1", False),
])
def test_github_ranges_read_exactly(adv, v, rng, want):
    assert adv.github_range_holds(v, rng) is want, f"{v} vs {rng!r}"


@pytest.mark.parametrize("v", ["latest", "master", "sha-d554c47", "{{ apex_version }}", ""])
def test_a_version_that_is_not_one_is_refused(adv, v):
    with pytest.raises(ValueError):
        adv.parse_version(v)


# --- receptor coverage -------------------------------------------------------

def test_every_pin_has_a_receptor(adv):
    cov = adv.coverage(adv.pins(), adv.receptors())
    assert not cov["missing"], (
        f"pins with no row in state/genome/advisory-receptors.yml: {cov['missing']}. "
        "Add {github: owner/repo} | {osv: purl} | {tech: slug} | {none: reason} for each.")
    assert not cov["stale"], f"receptor rows whose pin is gone: {cov['stale']}"
    assert not cov["malformed"], f"receptor rows that are not one of the four kinds: {cov['malformed']}"


def test_a_new_pin_without_a_receptor_fails_by_name(adv):
    pins = {**adv.pins(), "zebra_version": "1.0.0"}
    assert adv.coverage(pins, adv.receptors())["missing"] == ["zebra_version"]


def test_pins_come_from_the_layers_not_a_copy(adv):
    """The version is the pin's, read through nos_identity.default_layers()."""
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni
    layered = ni.default_config()
    for var, v in adv.pins().items():
        assert layered[var] == v
    rec = (REPO / "state/genome/advisory-receptors.yml").read_text(encoding="utf-8")
    assert "1.13." not in rec, "a version was copied into the receptors file"


def test_a_malformed_receptor_is_named(adv):
    cov = adv.coverage({"a_version": "1"}, {"a_version": {"pypi": "x"}})
    assert cov["malformed"] == ["a_version"]


# --- every source UNKNOWN on its own -----------------------------------------

def test_every_source_is_unknown_when_nothing_answers(adv):
    rep = adv.collect(fetch=_refuse)
    for name, src in rep["sources"].items():
        assert src["state"] == "UNKNOWN", f"source {name} said {src['state']} with nothing reachable"
    asked = [p for p in rep["pins"] if p["receptor"]["kind"] in ("github", "osv")
             and "floating" not in p["receptor"]]
    assert asked and all(p["state"] == "UNKNOWN" for p in asked), \
        [p["var"] for p in asked if p["state"] != "UNKNOWN"]
    assert rep["lockfiles"] and all(lf["state"] == "UNKNOWN" for lf in rep["lockfiles"])
    assert not any(p["state"] == "clear" for p in rep["pins"])
    text = adv.render(rep).lower()
    assert "no findings" not in text and "clear" not in text
    assert "unknown" in text


def test_one_source_down_leaves_the_others_standing(adv):
    payload = json.loads((FIXTURES / "github-php-frankenphp.json").read_text(encoding="utf-8"))

    def only_github(url, body=None):
        if url.startswith(FRANKENPHP):
            return payload if "page=1" in url or "page=" not in url else []
        raise OSError("down")

    rep = adv.collect(pin_values={"frankenphp_version": "1.13.1", "jupyterhub_version": "5.0.0"},
                      receptor_map={"frankenphp_version": {"github": "php/frankenphp"},
                                    "jupyterhub_version": {"osv": "pkg:pypi/jupyterhub"}},
                      lockfiles={}, fetch=only_github)
    by = {p["var"]: p for p in rep["pins"]}
    assert rep["sources"]["github"]["state"] == "OK"
    assert rep["sources"]["osv"]["state"] == "UNKNOWN"
    assert by["frankenphp_version"]["state"] == "affected"
    assert by["jupyterhub_version"]["state"] == "UNKNOWN"


def test_the_reader_exits_zero_offline(adv, monkeypatch, capsys):
    monkeypatch.setattr(adv, "fetch", _refuse)
    assert adv.main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "UNKNOWN"


# --- the FrankenPHP case -----------------------------------------------------

def _frankenphp(adv, version):
    payload = json.loads((FIXTURES / "github-php-frankenphp.json").read_text(encoding="utf-8"))

    def stub(url, body=None):
        if url.startswith(FRANKENPHP):
            return payload if "page=1" in url or "page=" not in url else []
        raise AssertionError(f"unexpected fetch {url}")  # GHSA-only ids: cve.now is not asked

    rep = adv.collect(pin_values={"frankenphp_version": version},
                      receptor_map={"frankenphp_version": {"github": "php/frankenphp"}},
                      lockfiles={}, fetch=stub)
    (pin,) = rep["pins"]
    return rep, pin


def test_frankenphp_1_13_1_hears_all_four(adv):
    rep, pin = _frankenphp(adv, "1.13.1")
    assert pin["state"] == "affected"
    assert {m["id"] for m in pin["matches"]} == FOUR
    assert pin["published"] == 7
    high = [m for m in pin["matches"] if m["id"] == "GHSA-6q3j-62j9-f9hh"]
    assert high[0]["severity"] == "high" and high[0]["fixed"] == "1.13.2"
    assert rep["verdict"] == "AFFECTED"


def test_frankenphp_1_13_3_hears_none_and_says_what_it_read(adv):
    rep, pin = _frankenphp(adv, "1.13.3")
    assert pin["matches"] == []
    assert pin["state"] == "clear" and pin["published"] == 7
    assert "no findings" not in adv.render(rep).lower()


def test_a_ghsa_only_match_says_kev_is_not_looked_up(adv):
    _, pin = _frankenphp(adv, "1.13.1")
    for m in pin["matches"]:
        assert m["kev"] is None and "no CVE id" in m["kev_reason"]


# --- lockfiles through OSV (synthetic) ---------------------------------------

def test_a_lockfile_hit_is_rematched_exactly(adv, tmp_path):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "face"},
        "node_modules/lodash": {"version": "4.17.20"},
        "node_modules/a/node_modules/left-pad": {"version": "1.3.0"},
    }}), encoding="utf-8")
    details = {
        "GHSA-real": {"id": "GHSA-real", "aliases": ["CVE-2021-23337"],
                      "database_specific": {"severity": "HIGH"},
                      "affected": [{"package": {"ecosystem": "npm", "name": "lodash"},
                                    "ranges": [{"type": "SEMVER", "events": [
                                        {"introduced": "0"}, {"fixed": "4.17.21"}]}]}]},
        "GHSA-server-only": {"id": "GHSA-server-only", "aliases": [],
                             "affected": [{"package": {"ecosystem": "npm", "name": "lodash"},
                                           "ranges": [{"type": "SEMVER", "events": [
                                               {"introduced": "5.0.0"}]}]}]},
    }

    def stub(url, body=None):
        if url.endswith("/v1/querybatch"):
            q = json.loads(body)["queries"]
            names = [x["package"]["name"] for x in q]
            return {"results": [{"vulns": [{"id": "GHSA-real"}, {"id": "GHSA-server-only"}]}
                                if n == "lodash" else {} for n in names]}
        if "/v1/vulns/" in url:
            return details[url.rsplit("/", 1)[1]]
        if url.startswith("https://cve.now/api/v1/entries/"):
            return {"id": "CVE-2021-23337", "exploitation": {"kev": None, "epssReached": None}}
        raise AssertionError(url)

    rep = adv.collect(pin_values={}, receptor_map={},
                      lockfiles={"face": (lock, "npm")}, fetch=stub)
    (lf,) = rep["lockfiles"]
    assert lf["state"] == "affected" and lf["packages"] == 2
    assert [(m["package"], m["id"]) for m in lf["matches"]] == [("lodash", "GHSA-real")]
    assert lf["matches"][0]["cve"] == "CVE-2021-23337" and lf["matches"][0]["kev"] is False
    assert lf["server_only"] == ["GHSA-server-only"]


def test_the_github_token_goes_only_to_github(adv, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    assert "Authorization" in adv.headers_for("https://api.github.com/repos/a/b/security-advisories")
    for url in ("https://api.osv.dev/v1/querybatch", "https://cve.now/api/v1/entries/CVE-1"):
        assert "Authorization" not in adv.headers_for(url)
