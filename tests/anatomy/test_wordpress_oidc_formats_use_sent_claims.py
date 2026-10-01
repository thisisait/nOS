"""Gate: the WordPress OIDC formats name only claims Authentik sends.

2026-10-01: displayname_format '{given_name} {family_name}' — Authentik's profile
scope has no family_name, so every SSO login failed with incomplete-user-claim.
"""
import re
from pathlib import Path

MU = Path(__file__).resolve().parents[2] / "roles/pazny.wordpress/files/oidc-mu-plugin.php"
# Authentik's default openid/email/profile scope mappings
SENT = {"sub", "email", "email_verified", "name", "given_name", "preferred_username", "nickname", "groups"}


def test_every_format_claim_is_sent():
    formats = re.findall(r"'\w+_format'\s*=>\s*'([^']*)'", MU.read_text())
    assert formats
    used = {c for f in formats for c in re.findall(r"\{(\w+)\}", f)}
    assert used <= SENT, used - SENT
