# 56 — A catalog flag that seeds nothing

**Found** by idea/06 and RELEASE.md long before the audit; **closed**
2026-09-03 by deletion.

`keap_nos_full_catalog` — declared in default.config.yml, set true by
profiles/all-on.yml, consumed by NOTHING. RELEASE.md even admitted it in
writing ("read by nothing") and the flag lived on. The toggle gate could not
see it: its regex harvests `install_*`/`configure_*` only.

Close: deleted from both files. The general class (a boolean outside the
gate's prefix set) is real but small — widen the toggle gate's regex the next
time any non-install boolean ships dead, not speculatively today.
