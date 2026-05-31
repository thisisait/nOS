#!/usr/bin/env python3
"""Generate the GDPR Article-30 DPA register (`state/dpa-register.md`).

The Data Processing Agreement register is the auditable artifact an operator
hands to their DPO: one Record of Processing Activities (Article 30(1)) entry
per nOS service, derived from the per-plugin `gdpr:` blocks (Tier-1) and the
Tier-2 app manifests. Source-of-truth mapping lives in
`files/anatomy/module_utils/nos_gdpr.py`; this tool only renders it, so the
markdown register and Wing's live `gdpr_processing` table never disagree.

Usage:
  python3 tools/gdpr-dpa-register.py            # write state/dpa-register.md
  python3 tools/gdpr-dpa-register.py --check     # exit 1 if committed file is stale
  python3 tools/gdpr-dpa-register.py --stdout     # print, don't write

CI-runnable: no Docker, no running Wing, no DB. The committed file is pinned
by tests/anatomy/test_gdpr_register_coverage.py.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "files/anatomy"))
from module_utils import nos_gdpr  # noqa: E401

OUT = REPO / "state/dpa-register.md"

# Stack display order — infra/observability first (always-on), then the rest.
STACK_ORDER = ["infra", "observability", "iiab", "apps", "devops",
               "b2b", "voip", "engineering", "data"]


def _stack_key(rec: dict) -> tuple:
    s = rec.get("stack")
    idx = STACK_ORDER.index(s) if s in STACK_ORDER else len(STACK_ORDER)
    return (idx, s or "~host", rec["id"])


def _yesno(v) -> str:
    return "**Yes**" if v else "No"


def _join(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items) if items else "—"


def _controller_lines() -> list[str]:
    """Art-30(1)(a) controller + DPO identity block. Reads GDPR_CONTROLLER_NAME
    / GDPR_DPO_NAME / GDPR_DPO_CONTACT from the environment; unset → deterministic
    placeholder lines so the committed register's byte-identity gate holds with
    no env set. Populate via a STANDALONE step: export the three vars + re-run
    this tool (not wired into a playbook profile yet)."""
    name = os.environ.get("GDPR_CONTROLLER_NAME") or ""
    dpo = os.environ.get("GDPR_DPO_NAME") or ""
    contact = os.environ.get("GDPR_DPO_CONTACT") or ""

    def _v(v: str, var: str) -> str:
        return v if v else f"_(unset — export {var})_"

    return [
        "## Controller & DPO (Art. 30(1)(a))",
        "",
        f"- **Controller:** {_v(name, 'GDPR_CONTROLLER_NAME')}",
        f"- **DPO / contact point:** {_v(dpo, 'GDPR_DPO_NAME')}",
        f"- **DPO contact:** {_v(contact, 'GDPR_DPO_CONTACT')}",
        "",
        "_Standalone step: export the three `GDPR_*` env vars and re-run "
        "`tools/gdpr-dpa-register.py` to populate (not set by any playbook profile yet)._",
        "",
    ]


def render(records: list[dict]) -> str:
    records = sorted(records, key=_stack_key)
    n = len(records)
    n_generated = sum(1 for r in records if r.get("purpose_generated"))
    n_transfers = sum(1 for r in records if r["transfers_outside_eu"])
    with_processors = [r for r in records if r["processors"]]
    bases: dict[str, int] = {}
    for r in records:
        bases[r["legal_basis"]] = bases.get(r["legal_basis"], 0) + 1

    L: list[str] = []
    L.append("# nOS — GDPR Record of Processing Activities (Article 30)")
    L.append("")
    L.append("> **Generated** by `tools/gdpr-dpa-register.py` from the per-plugin")
    L.append("> `gdpr:` blocks (Tier-1) and `apps/*.yml` manifests (Tier-2).")
    L.append("> **Do not edit by hand** — change the source `gdpr:` block and")
    L.append("> regenerate. Pinned by `tests/anatomy/test_gdpr_register_coverage.py`.")
    L.append(">")
    L.append("> This is the controller-side Record of Processing Activities a DPO")
    L.append("> reviews under GDPR Art. 30(1). Every service is self-hosted on the")
    L.append("> operator's own host; absent a declared processor (see below), there")
    L.append("> is no third-party data processor and no transfer outside the EU.")
    L.append("")
    L.extend(_controller_lines())
    L.append("## Summary")
    L.append("")
    L.append(f"- **Processing activities:** {n} "
             f"({sum(1 for r in records if r['tier'] == 'core')} core services, "
             f"{sum(1 for r in records if r['tier'] == 'app')} Tier-2 apps)")
    L.append("- **Legal basis (Art. 6(1)):** "
             + ", ".join(f"{k} ({v})" for k, v in sorted(bases.items())))
    L.append(f"- **Transfers outside the EU:** {n_transfers} "
             f"{'activity' if n_transfers == 1 else 'activities'}")
    L.append(f"- **Activities engaging a third-party processor:** {len(with_processors)}")
    if n_generated:
        L.append(f"- ⚠️ **{n_generated} activities** carry an auto-generated purpose "
                 f"(plugin `gdpr.purpose` not yet authored) — flagged with † below.")
    L.append("")

    # ── Cross-border + processor callout (the audit-sensitive subset) ──
    L.append("## Transfers & processors (audit-sensitive subset)")
    L.append("")
    if not with_processors and not n_transfers:
        L.append("None. Every processing activity is fully EU-resident and "
                 "self-hosted with no third-party processor.")
    else:
        L.append("| Service | Outside EU? | Processors |")
        L.append("|---|---|---|")
        for r in records:
            if r["transfers_outside_eu"] or r["processors"]:
                L.append(f"| {r['name']} (`{r['id']}`) | "
                         f"{_yesno(r['transfers_outside_eu'])} | "
                         f"{_join(r['processors'])} |")
    L.append("")

    # ── Security measures (Art. 32) ──
    L.append("## Security measures (Art. 32 — platform baseline)")
    L.append("")
    L.append("Inherited by every activity unless its `gdpr.security_measures`")
    L.append("overrides them. Authoritative prose: `docs/security-baseline.md`.")
    L.append("")
    for m in nos_gdpr.PLATFORM_SECURITY_MEASURES:
        L.append(f"- {m}")
    L.append("")

    # ── Per-stack processing records ──
    L.append("## Processing records")
    last_stack = object()
    for r in records:
        stack = r.get("stack") or "host / non-stack"
        if stack != last_stack:
            L.append("")
            L.append(f"### {stack} stack" if r.get("stack") else "### host / non-stack")
            last_stack = stack
        dagger = " †" if r.get("purpose_generated") else ""
        L.append("")
        L.append(f"#### {r['name']} — `{r['id']}`{dagger}")
        L.append(f"- **Purpose:** {r['purpose']}")
        L.append(f"- **Legal basis (Art. 6):** `{r['legal_basis']}`")
        L.append(f"- **Data subjects:** {_join(r['data_subjects'])}")
        L.append(f"- **Data categories:** {_join(r['data_categories'])}")
        L.append(f"- **Recipients / processors:** {_join(r['processors'])}")
        L.append(f"- **Transfers outside EU:** {_yesno(r['transfers_outside_eu'])}")
        L.append(f"- **Retention:** {nos_gdpr._retention_human(r['retention_days'])}")
        L.append(f"- **Storage:** {r['storage_location']}")
        sm = r["security_measures"]
        is_baseline = sm == nos_gdpr.PLATFORM_SECURITY_MEASURES
        L.append("- **Security measures:** platform baseline (see above)"
                 if is_baseline else f"- **Security measures:** {_join(sm)}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed register is stale")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args()

    content = render(nos_gdpr.all_records(REPO))

    if args.stdout:
        sys.stdout.write(content)
        return 0
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != content:
            sys.stderr.write(
                "state/dpa-register.md is STALE — run "
                "`python3 tools/gdpr-dpa-register.py` and commit.\n")
            return 1
        print("state/dpa-register.md is up to date.")
        return 0

    OUT.write_text(content)
    print(f"Wrote {OUT.relative_to(REPO)} "
          f"({content.count(chr(10))} lines, {len(nos_gdpr.all_records(REPO))} records).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
