"""WordPress is the gated client portal, not the books.

Week-1 commons pin: the estate already runs WordPress (native_oidc). It is
the client-facing surface. Ceiling is statements / shareable PDFs / contact
form. KEAP invoice verify, journals, and Espo deals stay out of this plugin.

RETRO-RED: the pre-pin wordpress-base GDPR subjects omit clients and the
hub card still says "Public website / blog". A later author who wires
pending-invoice-verify / journal-entry / posting as a WordPress write
fails the grep below.

CI-safe: plugin.yml + tree greps. No live WP, no KEAP dump, no nos.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "files" / "anatomy" / "plugins" / "wordpress-base"
PLUGIN = PLUGIN_DIR / "plugin.yml"

# Exact table/queue names the books write. Substring match so a compose
# write target or a pulse writes: block cannot sneak in unnamed.
BOOK_WRITE_TOKENS = (
    "pending-invoice-verify",
    "journal-entry",
    "posting",
)


def _manifest() -> dict:
    return yaml.safe_load(PLUGIN.read_text(encoding="utf-8"))


def test_gdpr_names_clients_and_the_portal_ceiling():
    gdpr = _manifest()["gdpr"]
    subjects = gdpr["data_subjects"]
    assert "clients" in subjects, (
        "wordpress-base GDPR subjects omit clients — the gated portal "
        "processes client PII (statements, PDFs, contact form)"
    )
    purpose = gdpr["purpose"]
    assert "portal" in purpose.lower()
    assert "not the books" in purpose.lower()
    blob = purpose.lower()
    assert "statement" in blob or "pdf" in blob
    assert "contact" in blob


def test_hub_card_names_the_portal_not_a_public_blog():
    card = _manifest()["ui-extension"]["hub_card"]
    desc = card["description"]
    assert "Public website / blog" not in desc
    lower = desc.lower()
    assert "portal" in lower
    assert "not the books" in lower


def test_sso_stays_native_oidc_at_declared_tier():
    auth = _manifest()["authentik"]
    assert auth["mode"] == "native_oidc"
    assert auth["tier"] == 4


def test_wordpress_base_does_not_write_the_books():
    hits: list[str] = []
    for path in PLUGIN_DIR.rglob("*"):
        if not path.is_file() or path.suffix in {".png", ".jpg", ".woff", ".woff2"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in BOOK_WRITE_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(REPO)}:{token}")
    assert not hits, (
        "wordpress-base names a books write surface "
        f"{hits} — WP is the portal, not pending-invoice-verify / journals / posting"
    )
