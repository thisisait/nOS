"""Anatomy gate — CSRF protection on every browser POST form (SEC-14, 2026-05-23).

Audit's H1 critical: pre-SEC-14, every state-changing form in Wing was
hand-rolled `<form method="post">` with no anti-CSRF nonce. A logged-in
super-admin operator visiting evil.com would have a hidden auto-submitting
form POST to https://wing.<tld>/admin/halt, /users/invite-create,
/approvals/approve/<id>, etc. The Authentik session cookie (SameSite=Lax
by default) rides along on top-level POST navigation = full RBAC bypass
via the operator's own browser.

Defense: BasePresenter::requirePostMethod() now validates a session-bound
CSRF token in addition to enforcing POST method. Token minted via
`bin2hex(random_bytes(32))` on first use; lives in Nette session
section 'csrf'; reused across all forms within the operator's session.
Templates emit it as a hidden input named `_csrf` via `{$csrfToken}`
populated by BasePresenter::beforeRender.

Validation:
  * Server: hash_equals timing-safe compare. Missing or wrong → 403.
  * Client: every `<form method="post">` must emit `_csrf` hidden input.

This gate pins:
  * BasePresenter declares getCsrfToken + validateCsrfToken methods
  * requirePostMethod calls validateCsrfToken
  * beforeRender exposes $csrfToken to templates
  * EVERY POST form in Wing templates carries the hidden _csrf input
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "files/anatomy/wing/app/Templates"
BASE = REPO / "files/anatomy/wing/app/Presenters/BasePresenter.php"


def test_base_presenter_declares_csrf_methods():
	src = BASE.read_text()
	assert "getCsrfToken" in src, "BasePresenter must declare getCsrfToken"
	assert "validateCsrfToken" in src, "BasePresenter must declare validateCsrfToken"
	# Token must be crypto-strong.
	assert "random_bytes(32)" in src, \
		"CSRF token must use random_bytes(32) for 256-bit entropy"
	# Compare must be timing-safe.
	assert "hash_equals" in src, "CSRF validation must use hash_equals (timing-safe)"


def test_require_post_method_validates_csrf():
	"""requirePostMethod is THE chokepoint for every state-changing
	action; CSRF check must be inside it."""
	src = BASE.read_text()
	m = re.search(
		r"protected function requirePostMethod\(\): void\s*\{(.*?)\n\t\}",
		src,
		re.DOTALL,
	)
	assert m, "requirePostMethod method not found"
	body = m.group(1)
	assert "validateCsrfToken" in body, \
		"requirePostMethod must call validateCsrfToken (defense-in-depth, not optional)"


def test_before_render_exposes_csrf_token():
	"""Templates need `$csrfToken` to render the hidden input. Exposed
	via beforeRender so every BasePresenter subclass gets it for free."""
	src = BASE.read_text()
	m = re.search(
		r"public function beforeRender\(\): void\s*\{(.*?)\n\t\}",
		src,
		re.DOTALL,
	)
	assert m, "beforeRender method not found"
	body = m.group(1)
	assert "csrfToken" in body, \
		"beforeRender must set template->csrfToken from getCsrfToken()"


def test_every_post_form_has_csrf_input():
	"""Sweep every Latte template under app/Templates/ — for each
	`<form method="post">` (including indented variants), assert there's
	a `<input type="hidden" name="_csrf" ...>` line in the next ~150
	chars. Pin per-file to make CI failure trace point to the exact
	template missing the input."""
	violations = []
	form_re = re.compile(
		r"<form\b[^>]*method=[\"']post[\"'][^>]*>",
		re.IGNORECASE | re.DOTALL,
	)
	for path in TEMPLATES.rglob("*.latte"):
		src = path.read_text()
		for m in form_re.finditer(src):
			# Look ahead up to 200 chars for the CSRF input.
			ahead = src[m.end() : m.end() + 250]
			if 'name="_csrf"' not in ahead and "name='_csrf'" not in ahead:
				rel = path.relative_to(REPO)
				violations.append(
					f"{rel}: <form method=\"post\"> at offset {m.start()} "
					f"missing `<input … name=\"_csrf\" …>` within 250 chars"
				)
	assert not violations, (
		"Every browser POST form MUST emit a `_csrf` hidden input. Found:\n  "
		+ "\n  ".join(violations)
	)


def test_csrf_input_uses_template_variable_not_hardcoded():
	"""The hidden input must use the {$csrfToken} template variable, not
	a hardcoded value. Otherwise the token's session-bound rotation
	can't propagate to the template."""
	for path in TEMPLATES.rglob("*.latte"):
		src = path.read_text()
		for m in re.finditer(r'<input[^>]*name="_csrf"[^>]*>', src):
			tag = m.group(0)
			assert "{$csrfToken}" in tag or "{=$csrfToken}" in tag, (
				f"{path.relative_to(REPO)}: _csrf input must reference "
				f"{{$csrfToken}} template variable. Found: {tag}"
			)


def test_csrf_input_not_inside_link_macro():
	"""Regression gate for the 8474f33 (SEC-14) breakage: the `_csrf`
	hidden input was dropped INSIDE a `{plink ...}` macro's argument list
	(on forms whose action took a trailing `param => $value`). Latte then
	tried to parse the raw `<input>` HTML as part of the PHP expression →
	render error at runtime.

	Correct placement: the `_csrf` input is the FIRST CHILD of the
	`<form>`, never a token inside `{plink}` / `{link}`. This gate fails
	if `_csrf` ever appears between an unclosed `{plink`/`{link` and its
	closing `}` — i.e. the macro-relative position the textual-presence
	check (test_every_post_form_has_csrf_input) cannot see."""
	macro_re = re.compile(r"\{p?link[^}]*_csrf[^}]*\}")
	violations = []
	for path in TEMPLATES.rglob("*.latte"):
		src = path.read_text()
		for m in macro_re.finditer(src):
			line = src.count("\n", 0, m.start()) + 1
			rel = path.relative_to(REPO)
			violations.append(
				f"{rel}:{line}: `_csrf` found inside a {{plink}}/{{link}} "
				f"macro — must be the first child of <form>, not a macro "
				f"argument. Offending macro: {m.group(0)[:120]}"
			)
	assert not violations, (
		"`_csrf` input must NEVER live inside a {plink}/{link} macro "
		"(breaks Latte parsing — see SEC-14 regression). Found:\n  "
		+ "\n  ".join(violations)
	)
