"""Anatomy gate — Nette parent-method shadowing as static (2026-05-17).

PHP 8.x refuses any subclass that declares a method `static` when the
parent declares the same name non-static (and vice versa) — it's a
fatal at class-load time. Nette\\Application\\UI\\Presenter is the
parent of every page in app/Presenters/, and several of its methods
have names that look generic enough to accidentally reuse as helper
names in a subclass.

Bug we hit live (2026-05-17 playbook run): ApprovalsPresenter declared
`private static function canonicalize()` as a JSON-canonicalization
helper. Nette's parent has `canonicalize()` non-static — class load
fails with:

    Cannot make non static method Nette\\Application\\UI\\Presenter
    ::canonicalize() static in class App\\Presenters\\ApprovalsPresenter

The cascading effect was nasty: every CLI tool that loads the Nette
DI container (bin/ingest-registry.php, bin/dispatch-notifications.php,
bin/run-agent.php) crashed at class-load, breaking the wing role's
post-task chain mid-playbook.

This gate forbids the shadowing pattern by name. The reserved list is
the set of Nette UI Presenter methods most likely to collide.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESENTERS_DIR = REPO / "files/anatomy/wing/app/Presenters"

# Methods that exist as non-static on Nette\Application\UI\Presenter
# (and its abstract bases). Adding to this list is fine; removing
# requires verifying the method really has been dropped upstream.
RESERVED_PARENT_METHODS = {
	"canonicalize",
	"redirect",
	"redirectPermanent",
	"redirectUrl",
	"terminate",
	"forward",
	"sendPayload",
	"sendResponse",
	"sendTemplate",
	"sendJson",
	"startup",
	"beforeRender",
	"afterRender",
	"shutdown",
	"getName",
	"getAction",
	"getView",
	"getHttpRequest",
	"getHttpResponse",
	"getRequest",
	"getSession",
	"getUser",
	"getContext",
	"getParameter",
	"isAjax",
	"link",
	"lazyLink",
	"createTemplate",
	"saveGlobalState",
	"loadState",
	"saveState",
}


def _iter_presenter_files():
	for php in PRESENTERS_DIR.rglob("*.php"):
		yield php


def test_no_static_override_of_nette_parent_method():
	"""For every PHP file under app/Presenters/, no `static function
	<NAME>` may appear where <NAME> is a Nette parent method — PHP
	would refuse to load the class."""
	pattern = re.compile(
		r"\b(public|private|protected)\s+static\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
	)
	offenders: list[tuple[str, str, int]] = []
	for php in _iter_presenter_files():
		text = php.read_text()
		for line_no, line in enumerate(text.splitlines(), 1):
			m = pattern.search(line)
			if not m:
				continue
			name = m.group(2)
			if name in RESERVED_PARENT_METHODS:
				offenders.append(
					(str(php.relative_to(REPO)), name, line_no),
				)
	assert not offenders, (
		"static function declared with a Nette parent-method name — "
		f"PHP will refuse to load the class. Rename the helper: {offenders}"
	)


# The file-specific regression pin (test_approvals_presenter_uses_canonicalize_json_alias)
# died with its subject: ApprovalsPresenter was retired on 2026-08-08 (A11 →
# agents-inbox; see test_approval_queue_event_backed.py). The general scan
# above still refuses a `static function canonicalize(` — or any other
# reserved-parent-method shadow — in EVERY presenter, which is the property
# that mattered; the deleted test only named the historical offender.
