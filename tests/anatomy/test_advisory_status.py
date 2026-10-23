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
    pins = adv.pins()
    for var, row in adv.receptors().items():
        copied = [v for v in map(str, row.values()) if pins.get(var) and pins[var] in v.split()]
        assert not copied and "version" not in row, f"{var}: the version was copied into its receptor row"


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


# --- review findings (CodeRabbit, PR #63) ------------------------------------

def _osv_pin(adv, detail):
    def stub(url, body=None):
        if url.endswith("/v1/querybatch"):
            return {"results": [{"vulns": [{"id": "GHSA-x"}]}]}
        if url.endswith("/v1/vulns/GHSA-x"):
            return detail
        raise OSError(url)
    rep = adv.collect(pin_values={"jupyterhub_version": "5.0.0"},
                      receptor_map={"jupyterhub_version": {"osv": "pkg:pypi/jupyterhub"}},
                      lockfiles={}, fetch=stub)
    (pin,) = rep["pins"]
    return rep, pin


def test_an_osv_record_not_tied_to_the_package_is_unknown_not_clear(adv):
    """OSV named the id for this query, but no affected entry carries our purl."""
    _, pin = _osv_pin(adv, {"id": "GHSA-x", "affected": [
        {"package": {"ecosystem": "PyPI", "name": "jupyterhub"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "5.1.0"}]}]}]})
    assert pin["state"] == "UNKNOWN", pin
    assert pin["unreadable"] == ["GHSA-x"]


def test_a_bad_version_in_one_osv_record_leaves_the_report_standing(adv):
    rep, pin = _osv_pin(adv, {"id": "GHSA-x", "affected": [
        {"package": {"purl": "pkg:pypi/jupyterhub"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "next-release"}]}]}]})
    assert pin["state"] == "UNKNOWN" and pin["unreadable"] == ["GHSA-x"]
    assert rep["sources"]["osv"]["state"] == "UNKNOWN"


def test_server_only_ids_are_shown(adv):
    rep, pin = _osv_pin(adv, {"id": "GHSA-x", "affected": [
        {"package": {"purl": "pkg:pypi/jupyterhub"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "6.0.0"}]}]}]})
    assert pin["state"] == "clear" and pin["server_only"] == ["GHSA-x"]
    assert "1 OSV id(s) not re-matched" in adv.render(rep)


def test_a_github_hit_names_the_package_it_matched(adv):
    _, pin = _frankenphp(adv, "1.13.1")
    assert {(m["package"], m["ecosystem"]) for m in pin["matches"]} == {("github.com/dunglas/frankenphp", "go")}


# --- operator live-run review (PR #63, 2026-10-23) ---------------------------

def _github_pin(adv, repo, fixture, version, payload=None):
    if payload is None:
        payload = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    base = f"https://api.github.com/repos/{repo}/security-advisories"

    def stub(url, body=None):
        if url.startswith(base):
            return payload if "page=1" in url else []
        raise AssertionError(f"unexpected fetch {url}")

    rep = adv.collect(pin_values={"x_version": version}, receptor_map={"x_version": {"github": repo}},
                      lockfiles={}, fetch=stub)
    return rep, rep["pins"][0]


@pytest.mark.parametrize("version, affected", [
    ("2026.5.7", False),   # patched on its own line (2026.5): the 2026.8 line's range does not reach it
    ("2026.5.6", True),
    ("2026.8.1", True),
    ("2026.8.2", False),
    ("2026.2.7", False),
    ("2025.12.0", True),   # no line of its own: the ranges still hold
])
def test_authentik_reads_each_release_line(adv, version, affected):
    _, pin = _github_pin(adv, "goauthentik/authentik", "github-goauthentik-authentik.json", version)
    assert (pin["state"] == "affected") is affected, pin
    if not affected:
        assert pin["state"] == "clear"


@pytest.mark.parametrize("version, affected", [
    ("v15.119.3", False),  # the estate's pin: patched on the 15 line, the 16 range does not apply
    ("v15.111.0", True),
    ("v16.22.9", True),
    ("v16.23.0", False),
])
def test_erpnext_reads_each_release_line(adv, version, affected):
    _, pin = _github_pin(adv, "frappe/erpnext", "github-frappe-erpnext.json", version)
    assert (pin["state"] == "affected") is affected, pin


def test_a_semver_minor_between_two_lines_stays_affected(adv):
    payload = [{"ghsa_id": "GHSA-a", "severity": "low", "vulnerabilities": [
        {"package": {"name": "p"}, "vulnerable_version_range": "< 1.5.0", "patched_versions": "1.5.0"},
        {"package": {"name": "p"}, "vulnerable_version_range": "< 1.3.9", "patched_versions": "1.3.9"}]}]
    _, pin = _github_pin(adv, "o/r", None, "1.4.0", payload)
    assert pin["state"] == "affected"


REDIS = [  # api.github.com/repos/redis/redis/security-advisories, transcribed 2026-10-23
    {"ghsa_id": "GHSA-jhjx-x4cf-4vm8", "severity": "high", "vulnerabilities": [
        {"package": {"name": "redis"}, "vulnerable_version_range": ">= 8.2.0", "patched_versions": "8.2.3"}]},
    {"ghsa_id": "GHSA-whxg-wx83-85p5", "severity": "high", "vulnerabilities": [
        {"package": {"name": "redis"}, "vulnerable_version_range": ">= 2.8.18",
         "patched_versions": "6.2.16, 7.2.6, 7.4.1"}]},
]


@pytest.mark.parametrize("version, affected", [
    ("8.10.1", False),  # the estate's pin: above every patch, a lower bound alone does not reach it (live false positive)
    ("8.2.2", True),
    ("8.2.3", False),
    ("7.4.0", True),
    ("7.4.1", False),
    ("7.3.0", True),    # a line between two patched lines has no patch of its own
])
def test_a_lower_bound_is_closed_by_its_patches(adv, version, affected):
    _, pin = _github_pin(adv, "redis/redis", None, version, REDIS)
    assert (pin["state"] == "affected") is affected, pin


@pytest.mark.parametrize("v, rng, want", [
    # grafana GHSA-mx47-6497-3fv2 and metabase GHSA-2wgg-7r2p-cmqx (live): a comma list of
    # several upper bounds is one bound per release line, not their AND
    ("12.4.10", "< 9.0.3, < 8.5.9, < 8.4.10, < 8.3.10, >= 5.3", False),
    ("8.5.8", "< 9.0.3, < 8.5.9, < 8.4.10, < 8.3.10, >= 5.3", True),
    ("8.5.9", "< 9.0.3, < 8.5.9, < 8.4.10, < 8.3.10, >= 5.3", False),
    ("8.2.0", "< 9.0.3, < 8.5.9, < 8.4.10, < 8.3.10, >= 5.3", True),   # an older line with no patch
    ("5.2.0", "< 9.0.3, < 8.5.9, < 8.4.10, < 8.3.10, >= 5.3", False),  # below the lower bound
    ("0.63.10", "<55.13, <56.3, <57.1", False),
    ("56.2", "<55.13, <56.3, <57.1", True),
])
def test_several_upper_bounds_are_one_per_line(adv, v, rng, want):
    assert adv.github_range_holds(v, rng) is want, f"{v} vs {rng!r}"


def test_an_open_range_with_no_patch_is_judged_not_counted(adv):
    """grafana GHSA-8xmm-x63g-f6xv ">=8.1", patched none, matched 12.4.10 live: an open range
    with no fix published cannot say the pin is affected; the pin says what to judge."""
    payload = [{"ghsa_id": "GHSA-open", "severity": "high", "vulnerabilities": [
        {"package": {"name": "p"}, "vulnerable_version_range": ">= 8.1", "patched_versions": ""}]}]
    _, pin = _github_pin(adv, "o/r", None, "12.4.10", payload)
    assert pin["state"] == "UNKNOWN" and "open-ended" in pin["reason"], pin
    assert [m["id"] for m in pin["matches"]] == ["GHSA-open"] and pin["matches"][0]["open"] is True


@pytest.mark.parametrize("v, want", [("3.17.0", False), ("1.0.1", True), ("1.0.2", False)])
def test_a_semicolon_joins_bounds(adv, v, want):
    """woodpecker GHSA-4gcf-5m39-98mc ">= 1.0.0; < 1.0.2" matched v3.17.0 live."""
    assert adv.github_range_holds(v, ">= 1.0.0; < 1.0.2") is want


@pytest.mark.parametrize("v, rng, want", [
    ("1.12.0", "v1.11.2=< <=v1.12.2", True),
    ("1.12.3", "v1.11.2=< <=v1.12.2", False),
    ("1.11.1", "v1.11.2=< <=v1.12.2", False),
    ("9.2.5", ">=9.2.0 <9.2.10 >=9.3.0 <9.3.4", True),
    ("9.2.10", ">=9.2.0 <9.2.10 >=9.3.0 <9.3.4", False),
    ("9.3.3", ">=9.2.0 <9.2.10 >=9.3.0 <9.3.4", True),
    ("9.3.4", ">=9.2.0 <9.2.10 >=9.3.0 <9.3.4", False),
    ("1.0.5", "1.0.0 - 1.1.1", True),
    ("1.1.1", "1.0.0 - 1.1.1", True),
    ("1.1.2", "1.0.0 - 1.1.1", False),
    ("2026.5.2", "≤ 2026.5.2", True),
    ("2026.5.3", "≤ 2026.5.2", False),
])
def test_the_range_forms_seen_live_parse(adv, v, rng, want):
    assert adv.github_range_holds(v, rng) is want, f"{v} vs {rng!r}"


def test_an_unreadable_range_raises(adv):
    with pytest.raises(ValueError):
        adv.github_range_holds("1.58.0", "x.58.0")


def _two_advisories(good):
    rows = [{"ghsa_id": "GHSA-bad", "severity": "low", "vulnerabilities": [
        {"package": {"name": "p"}, "vulnerable_version_range": "x.58.0", "patched_versions": ""}]}]
    if good:
        rows.append({"ghsa_id": "GHSA-good", "severity": "high", "vulnerabilities": [
            {"package": {"name": "p"}, "vulnerable_version_range": "<= 1.13.1", "patched_versions": "1.13.2"}]})
    return rows


def test_one_unreadable_advisory_does_not_blank_the_repo(adv):
    _, pin = _github_pin(adv, "o/r", None, "1.13.1", _two_advisories(good=True))
    assert pin["state"] == "affected"
    assert [m["id"] for m in pin["matches"]] == ["GHSA-good"]
    assert pin["unreadable"] == ["GHSA-bad"]


def test_only_unreadable_advisories_make_the_pin_unknown_with_a_count(adv):
    rep, pin = _github_pin(adv, "o/r", None, "1.13.1", _two_advisories(good=False))
    assert pin["state"] == "UNKNOWN"
    assert "1 advisories unreadable" in pin["reason"]
    assert rep["sources"]["github"]["state"] == "OK"


def test_github_pages_up_to_thirty(adv):
    assert adv.GITHUB_MAX_PAGES == 30


def test_the_report_counts_its_calls(adv):
    rep, _ = _frankenphp(adv, "1.13.1")
    assert rep["calls"] == 1
    assert "1 network call" in adv.render(rep)


def test_gh_token_is_used_when_github_token_is_not(adv, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "t0k")
    assert adv.headers_for("https://api.github.com/x")["Authorization"] == "Bearer t0k"
    assert "Authorization" not in adv.headers_for("https://cve.now/feed?tech=nginx&format=json")


# --- tech: receptors through the cve.now feed --------------------------------

NGINX_FEED = "https://cve.now/feed?tech=nginx&format=json"


def _tech(adv, version, receptor, feed, entries):
    def stub(url, body=None):
        if url.startswith("https://cve.now/feed?"):
            return feed.get(url, {"items": []})
        if url.startswith("https://cve.now/api/v1/entries/"):
            return entries[url.rsplit("/", 1)[1]]
        raise AssertionError(url)
    rep = adv.collect(pin_values={"apex_version": version}, receptor_map={"apex_version": receptor},
                      lockfiles={}, fetch=stub)
    return rep, rep["pins"][0]


ENTRIES = {
    "CVE-A": {"id": "CVE-A", "severity": {"cvss": 7.5},
              "exploitation": {"kev": {"dateAdded": "2026-10-01"}, "epssReached": None},
              "affected": [{"vendor": "F5", "product": "NGINX Open Source",
                            "ranges": [{"introduced": "1.25.0", "fixed": "1.30.5"}]}]},
    "CVE-B": {"id": "CVE-B", "exploitation": {},
              "affected": [{"vendor": "F5", "product": "NGINX Plus",
                            "ranges": [{"introduced": "R17", "fixed": "*"}]}]},
    "CVE-C": {"id": "CVE-C", "exploitation": {},
              "affected": [{"vendor": "F5", "product": "NGINX Open Source",
                            "ranges": [{"introduced": "1.11.4", "fixed": "*"}]}]},
    "CVE-D": {"id": "CVE-D", "exploitation": {},
              "affected": [{"vendor": "F5", "product": "NGINX Open Source",
                            "ranges": [{"introduced": "1.20.0", "fixed": "1.26.3"}]}]},
}


def test_a_tech_receptor_reads_the_feed_and_matches_its_product(adv):
    feed = {NGINX_FEED: {"items": [{"id": k} for k in ENTRIES]}}
    rep, pin = _tech(adv, "1.30.4-alpine@sha256:97d4",
                     {"tech": "nginx", "product": "NGINX Open Source"}, feed, ENTRIES)
    assert pin["state"] == "affected"
    (m,) = pin["matches"]
    assert m["id"] == "CVE-A" and m["fixed"] == "1.30.5" and m["kev"] is True
    assert pin["unreadable"] == ["CVE-C"]          # fixed "*": no bound to match against
    assert pin["published"] == 4
    assert "range ?" not in adv.render(rep)


def test_an_empty_tech_feed_stays_unknown(adv):
    _, pin = _tech(adv, "2.93", {"tech": "dnsmasq", "product": "dnsmasq"}, {}, {})
    assert pin["state"] == "UNKNOWN" and "feed is empty" in pin["reason"]


def test_a_tech_receptor_without_a_product_is_malformed(adv):
    """A cve.now feed mixes products: live, tech=postgresql matched psqlODBC and pgjdbc against
    postgresql 16.15, tech=wordpress matched plugins. Without its product a tech row matches nothing."""
    cov = adv.coverage({"a_version": "1"}, {"a_version": {"tech": "postgresql"}})
    assert cov["malformed"] == ["a_version"], cov
    _, pin = _tech(adv, "1.30.4", {"tech": "nginx"}, {NGINX_FEED: {"items": [{"id": "CVE-A"}]}}, ENTRIES)
    assert pin["state"] == "UNKNOWN" and "product" in pin["reason"], pin


def test_every_tech_receptor_names_its_product(adv):
    bare = [k for k, r in adv.receptors().items() if "tech" in r and not r.get("product")]
    assert not bare, f"tech receptors without a product (they would match every product in the feed): {bare}"


def test_a_tech_slug_cve_now_refuses_says_so(adv):
    def stub(url, body=None):
        raise adv.urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
    rep = adv.collect(pin_values={"m_version": "11.8.9"}, receptor_map={"m_version": {"tech": "mariadb", "product": "MariaDB"}},
                      lockfiles={}, fetch=stub)
    pin = rep["pins"][0]
    assert pin["state"] == "UNKNOWN" and "cve.now has no tech mariadb" in pin["reason"], pin


def test_a_tech_receptor_may_name_its_product(adv):
    cov = adv.coverage({"a_version": "1"}, {"a_version": {"tech": "nginx", "product": "NGINX Open Source"}})
    assert cov["malformed"] == []


# --- OSV rows say which range matched ----------------------------------------

def test_an_osv_hit_prints_its_range_and_fix(adv):
    detail = {"id": "GHSA-x", "affected": [
        {"package": {"purl": "pkg:pypi/jupyterhub"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "5.1.0"}]}]}]}
    rep, pin = _osv_pin(adv, detail)
    (m,) = pin["matches"]
    assert m["range"] == "< 5.1.0" and m["fixed"] == "5.1.0"
    text = adv.render(rep)
    assert "range < 5.1.0 fixed 5.1.0" in text and "range ?" not in text


# --- the ETag cache (operator ruling 2026-10-23: a library module) -----------
#
# The writes live in tools/_advisory_cache.py, which test_readers_section_only_reads
# cannot see (its documented blind spot). That was ruled on PR #63, not hidden:
# these cases pin what the cache may do instead.

class _Resp:
    def __init__(self, payload, etag=None):
        self._b = json.dumps(payload).encode()
        self.headers = {"ETag": etag} if etag else {}

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_304_is_answered_from_the_cache(adv, tmp_path, monkeypatch):
    import urllib.error
    seen = []

    def urlopen(req, timeout=None):
        seen.append(dict(req.header_items()))
        if len(seen) == 1:
            return _Resp([{"ghsa_id": "GHSA-1"}], etag='"abc"')
        raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)

    monkeypatch.setattr(adv.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    adv.use_cache(tmp_path / "c")
    try:
        url = "https://api.github.com/repos/o/r/security-advisories?per_page=100&page=1"
        assert adv.fetch(url) == [{"ghsa_id": "GHSA-1"}]
        assert adv.fetch(url) == [{"ghsa_id": "GHSA-1"}]
        assert seen[1].get("If-none-match") == '"abc"'
        assert adv.CACHE_STATS["not_modified"] == 1
        stored = "".join(p.read_text() for p in (tmp_path / "c").iterdir())
        assert "t0k" not in stored, "a token reached the cache"
    finally:
        adv.use_cache(None)


def test_no_cache_without_the_flag(adv):
    assert adv.CACHE is None


def test_a_cache_dir_inside_the_repo_is_refused(adv, monkeypatch, capsys):
    monkeypatch.setattr(adv, "fetch", _refuse)
    inside = REPO / "state" / "advisory-cache-test"
    assert adv.main(["--json", "--cache-dir", str(inside)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "refused" in out["cache_note"] and not inside.exists()
    assert adv.CACHE is None


def test_the_report_says_what_the_cache_answered(adv):
    rep, _ = _frankenphp(adv, "1.13.1")
    rep["cache_note"] = "; 1 answered 304 from cache"
    assert "1 network call(s); 1 answered 304 from cache" in adv.render(rep)
