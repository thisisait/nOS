# SSOT

> **PROPOSED, not settled.**

## 1. Address

`nos-sot:<realm>/<file>#<id>`

`<realm>` is a key of [`INDEX.yml`](../INDEX.yml).
A section number without a realm and a file is not an address.
A file with no numbered heading is addressed as the file only.

## 2. Location

A realm's bytes live at `realms.<name>.path`. One path per realm.
Never copy a realm into `ssot/<realm>` — that directory is a second tree.

## 3. Force

`in_force: true` is law. `in_force: false` is not.
A loop promotes a file into `ssot/doctrine/` when it is an article.
`docs/` is the warehouse the loop empties.
A **PROPOSED** banner on a file in an in-force realm means that file is not
law yet. The realm being in force does not settle the banner.

## 4. Tenant

Same INDEX keys. Prefix is not `nos-sot:`.
Bytes live in the tenant seed, not this tree.
Tenant agents (manager, auditor, accountant, mini-lawyer) read the tenant
prefix for tenant facts. They SHALL cite `nos-sot:` for estate rules they
reuse. They MUST NOT copy nOS articles into the tenant tree.

## 5. Citation

The article address is the numbered heading (`## 3`). Citing code and
warehouse docs write `§3` plus a path. The article does not repeat the glyph.
Numbered headings, once published, do not move.
A heading number MAY be assigned on promote only when the source had none
and no inbound `§N` existed.

## 6. Warehouse

Reuse recipes live in the `systems` realm (`docs/systems/`, not in force).
They SHALL cite `nos-sot:doctrine/<file>#<id>`. They MUST NOT restate the
rule. Extending nOS is reuse of a wired system (Metabase for visualisation,
the declared vector store for embeddings) until a fee proves it is not.
KEAP visualises the cite edges; it does not become a second constitution.
