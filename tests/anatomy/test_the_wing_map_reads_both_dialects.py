"""`wing-status` must see BOTH ways this codebase touches a table.

WHY THIS GATE EXISTS, and it is the tool's own history rather than a
hypothetical. `tools/wing-status.py` classifies every wing.db table as live,
empty or write-only by finding who writes and who reads it. Its first draft
matched SQL text only — `INSERT INTO t`, `FROM t` — and reported TEN tables as
write-only. Most of that was false: Wing's repositories use Nette's fluent
builder, `$this->db->table('agent_threads')->insert(...)`, which contains no SQL
at all. A detector that reads one spelling reports the other as absent, and an
absent reader reads as a dead table.

The second draft made the opposite error in the other column: it subtracted
writers from readers, so `gdpr_processing` — whose only reader is the repository
that also inserts into it — came back write-only again. Write-only has to mean
"read NOWHERE"; anything else reports a code layout rather than a fact about
the data.

Both mistakes are pinned below because the tool's whole value is the
write-only bucket, and a false entry there invites someone to delete a live
table. Everything runs against fixture strings; no wing.db is opened.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/wing-status.py"

_spec = importlib.util.spec_from_file_location("wing_status", TOOL)
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


def _classify(body: str, table: str = "agent_threads") -> dict[str, set[str]]:
    return ws._access([table], [("fixture.php", body)])[table]


def test_the_fluent_builder_counts_as_a_write() -> None:
    """The exact line the first draft could not see."""
    got = _classify("$this->db->table('agent_threads')->insert($row);")
    assert got["writers"] == {"fixture.php"}, (
        "a Nette fluent insert was not read as a write — every AgentKit and "
        "GDPR table would report as written by nothing")


def test_raw_sql_counts_as_a_write() -> None:
    got = _classify("$db->query('INSERT INTO agent_threads (uuid) VALUES (?)', $u);")
    assert got["writers"] == {"fixture.php"}


def test_a_reader_that_also_writes_still_counts_as_a_reader() -> None:
    """The second draft's error: a repository is not evidence of a dead table."""
    got = _classify(
        "$this->db->table('agent_threads')->insert($row);\n"
        "return $this->db->table('agent_threads')->order('id ASC');")
    assert got["readers"] == {"fixture.php"}, (
        "the only reader was dropped because the same file also writes — "
        "every table owned by one repository would report write-only")


def test_the_terminal_fetchers_count_as_reads() -> None:
    """`->get()` and `->fetchAll()` end a chain with no `select` in it, which is
    how GdprRepository and half of Wing's model layer actually read."""
    for verb in ("get(1)", "fetchAll()", "count('*')"):
        got = _classify(f"$this->db->table('agent_threads')->{verb};")
        assert got["readers"] == {"fixture.php"}, f"->{verb} was not a read"


def test_prose_about_a_table_is_neither() -> None:
    """A comment naming a table must not make it look alive. This is the whole
    reason the classifier looks for a VERB rather than for the name."""
    got = _classify("// agent_threads holds one row per conversation branch.\n"
                    "/** @see agent_threads */")
    assert got == {"writers": set(), "readers": set()}, (
        "a comment counted as access — the map would call every table live and "
        "the write-only bucket would be permanently empty")


def test_the_tool_does_not_scan_itself() -> None:
    """Its own docstring names tables beside `->insert(...)` as examples. A
    first run had wing-status.py listed as a writer of agent_threads."""
    assert TOOL.resolve() not in {REPO / p for p, _ in ws._files()}


def test_it_cannot_write() -> None:
    """A status command that could purge audit rows is a status command that
    will, one day, with the wrong argument."""
    src = TOOL.read_text(encoding="utf-8")
    assert "mode=ro" in src, "wing.db is not opened read-only"
    for verb in ("DELETE FROM", "DROP TABLE", "VACUUM", "INSERT INTO"):
        assert f'"{verb}' not in src and f"'{verb}" not in src, (
            f"{verb} appears as a statement in a reader")
