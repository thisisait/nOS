"""
tests/apps/test_coolify_importer.py — unit tests for tools/import-coolify-template.py.

We import the script as a module (it's stdlib-only) and exercise three
surfaces:
  1. parse_header — Coolify-style ``# key: value`` extraction
  2. rewrite_tokens — ${SERVICE_*} → $SERVICE_*_X mapping + operator-TODO list
  3. render_manifest — emits a draft that nos_app_parser will:
       (a) reject as long as gdpr.legal_basis = "TODO" (parser rejects unknown enum)
       (b) accept once the operator replaces TODO sentinels with real values

The fixture is a hand-rolled compose body, not a fetched URL — keeps the
test hermetic and CI-safe.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import textwrap
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "import-coolify-template.py"


def _load_module():
    """Load the importer script as a Python module so we can call its
    helpers directly. Hyphenated filename + module name handled by spec."""
    spec = importlib.util.spec_from_file_location("coolify_importer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def importer():
    return _load_module()


@pytest.fixture
def sample_template():
    """Coolify-flavoured fixture exercising every token rewrite path."""
    return textwrap.dedent("""\
        # documentation: https://example.com/docs
        # slogan: One-line app summary.
        # category: productivity
        # tags: pdf, signing, opensource
        # logo: svgs/example.svg
        # port: 3000

        services:
          example:
            image: example/example:1.0.0
            environment:
              - PUBLIC_URL=${SERVICE_URL_EXAMPLE_3000}
              - APP_URL=${SERVICE_URL_EXAMPLE}
              - FQDN=${SERVICE_FQDN_EXAMPLE}
              - DB_USER=${SERVICE_USER_POSTGRES}
              - DB_PASSWORD=${SERVICE_PASSWORD_POSTGRES}
              - SESSION_SECRET=${SERVICE_BASE64_SESSION}
              - LONGER_SECRET=${SERVICE_BASE64_64_DOUBLE}
              - SHORT_SECRET=${SERVICE_BASE64_32_SHORT}
              - SMTP_HOST=${SMTP_HOST}
              - DISABLE_SIGNUP=${DISABLE_SIGNUP:-false}
              - DB_NAME=${POSTGRES_DB:-example_db}
            volumes:
              - example-data:/data
        volumes:
          example-data:
        """)


# ─── parse_header ──────────────────────────────────────────────────────────

class TestParseHeader:
    def test_extracts_known_keys(self, importer, sample_template):
        h = importer.parse_header(sample_template)
        assert h["documentation"] == "https://example.com/docs"
        assert h["category"] == "productivity"
        assert h["port"] == "3000"
        assert h["tags"].startswith("pdf, signing")

    def test_stops_at_first_non_comment(self, importer):
        text = "# port: 3000\n\nservices:\n  app:\n    image: x\n"
        h = importer.parse_header(text)
        assert h == {"port": "3000"}

    def test_empty_when_no_header(self, importer):
        h = importer.parse_header("services:\n  app: {}\n")
        assert h == {}


# ─── rewrite_tokens ────────────────────────────────────────────────────────

class TestRewriteTokens:
    def test_service_url_with_port_to_fqdn(self, importer):
        body = "PUBLIC_URL=${SERVICE_URL_EXAMPLE_3000}"
        out, todos = importer.rewrite_tokens(body, "EXAMPLE")
        assert "https://$SERVICE_FQDN_EXAMPLE" in out
        assert "${" not in out
        assert todos == []

    def test_service_url_without_port(self, importer):
        body = "X=${SERVICE_URL_EXAMPLE}"
        out, _ = importer.rewrite_tokens(body, "EXAMPLE")
        assert out.strip() == "X=https://$SERVICE_FQDN_EXAMPLE"

    def test_user_password_passthrough(self, importer):
        body = "U=${SERVICE_USER_DB} P=${SERVICE_PASSWORD_DB}"
        out, _ = importer.rewrite_tokens(body, "APP")
        assert "$SERVICE_USER_DB" in out
        assert "$SERVICE_PASSWORD_DB" in out

    def test_base64_default_length_is_64(self, importer):
        body = "S=${SERVICE_BASE64_SESSION}"
        out, _ = importer.rewrite_tokens(body, "APP")
        assert "$SERVICE_BASE64_64_SESSION" in out

    def test_base64_explicit_length_preserved(self, importer):
        body = "A=${SERVICE_BASE64_32_SHORT} B=${SERVICE_BASE64_64_LONG}"
        out, _ = importer.rewrite_tokens(body, "APP")
        assert "$SERVICE_BASE64_32_SHORT" in out
        assert "$SERVICE_BASE64_64_LONG" in out

    def test_operator_env_collected_with_default(self, importer):
        body = "X=${DISABLE_SIGNUP:-false}\nY=${POSTGRES_DB:-app_db}"
        out, todos = importer.rewrite_tokens(body, "APP")
        # Stripped to bare $VAR
        assert "$DISABLE_SIGNUP" in out
        assert "${" not in out
        # And recorded with their defaults
        var_to_default = dict(todos)
        assert var_to_default["DISABLE_SIGNUP"] == "false"
        assert var_to_default["POSTGRES_DB"] == "app_db"

    def test_operator_env_without_default(self, importer):
        body = "Z=${SMTP_HOST}"
        out, todos = importer.rewrite_tokens(body, "APP")
        assert out.strip() == "Z=$SMTP_HOST"
        assert ("SMTP_HOST", "") in todos

    def test_operator_env_dedup(self, importer):
        body = "A=${X} B=${X} C=${X:-y}"
        _, todos = importer.rewrite_tokens(body, "APP")
        # X appears multiple times — only one TODO entry
        names = [name for name, _ in todos]
        assert names.count("X") == 1


# ─── render_manifest end-to-end ────────────────────────────────────────────

class TestRenderManifestEndToEnd:
    def test_round_trip_produces_parser_friendly_draft(
        self, importer, sample_template, tmp_path
    ):
        """The draft must be:
          1) syntactically valid YAML
          2) compose-wrapped so parser sees compose.services
          3) parser-rejected ONLY because legal_basis is "TODO"
          4) parser-accepted once the operator replaces TODOs
        """
        header = importer.parse_header(sample_template)
        body = importer.strip_header(sample_template)
        rewritten, todos = importer.rewrite_tokens(body, "EXAMPLE")
        manifest = importer.render_manifest(
            name="example",
            header=header,
            compose_body=rewritten,
            todos=todos,
            source_url="file:///fixture",
        )
        out_path = tmp_path / "example.yml.draft"
        out_path.write_text(manifest, encoding="utf-8")

        # Sanity: YAML loads
        import yaml
        loaded = yaml.safe_load(out_path.read_text())
        assert loaded["meta"]["name"] == "example"
        assert "compose" in loaded
        assert "services" in loaded["compose"]
        assert "example" in loaded["compose"]["services"]

        # Parser before edit — rejects on legal_basis = "TODO"
        sys.path.insert(0, str(REPO))
        try:
            from module_utils import nos_app_parser as p
        finally:
            sys.path.pop(0)

        with pytest.raises(p.AppParseError) as exc:
            p.parse_app_file(str(out_path))
        # The validation error names the offending field
        joined = "\n".join(exc.value.violations)
        assert "legal_basis" in joined

        # Parser after edit — operator replaces TODO sentinels with valid
        # values; the parser must accept (no exception, returns dict).
        text = out_path.read_text()
        text = text.replace('legal_basis: "TODO"',
                            'legal_basis: "legitimate_interests"')
        text = text.replace('- "TODO"', '- "ip_address"')
        out_path.write_text(text)

        record = p.parse_app_file(str(out_path))
        assert record["meta"]["name"] == "example"
        assert record["gdpr"]["legal_basis"] == "legitimate_interests"

    def test_operator_env_todos_visible_in_preamble(
        self, importer, sample_template
    ):
        header = importer.parse_header(sample_template)
        body = importer.strip_header(sample_template)
        rewritten, todos = importer.rewrite_tokens(body, "EXAMPLE")
        manifest = importer.render_manifest(
            name="example", header=header, compose_body=rewritten,
            todos=todos, source_url="file:///fixture",
        )
        # Both the WITH-default and WITHOUT-default vars appear in the preamble
        assert "SMTP_HOST" in manifest
        assert "DISABLE_SIGNUP" in manifest
        # And the WITHOUT-default var is flagged as REQUIRED
        assert "REQUIRED" in manifest
