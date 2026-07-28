# DataTables relations — the join that `ent:` needs

Authored 2026-07-28, ahead of the operator's first real business-data load through
face. Design only; nothing here is implemented.

Context: `cortex-self-core.md` §6b decided that **`ent:` resolves against
DataTables** and that `object_type_definitions` gets dropped. This file works out
what that costs, because the decision has a gap in it.

---

## 1. The gap, stated exactly

`shared/contracts/table.ts` defines eleven column kinds. Two already wire a row
into the knowledge graph:

| kind | points at |
| --- | --- |
| `taxonomyRef` | a taxonomy node id — anchors the row into the universe |
| `objectRef` | a `knowledge_objects.id` |

There is **no kind that points at another row.** A table can be anchored to the
universe but cannot be joined to a sibling table. An invoice cannot reference its
customer; a delivery address cannot belong to a party; a `nos-tenant-owner` cannot
own anything.

That is the whole blocker, and it is one column kind wide.

Everything else the join needs is already built and unused for this purpose:
per-user ownership, `visibility` mapped onto the Authentik tiers, `schema_json`
with zod validation on write, `table_row_history`, a driver abstraction
(`libsql | rustfs | postgres | grist`), declared `TableCapabilities`, and an
`AggregateQuery` with group-by dimensions and aggregated measures. The OLAP
surface exists; it just cannot cross a table boundary.

---

## 2. Two kinds of edge, and why one table cannot hold both

KEAP already has a `relations` table (migration `006-typed-relations`):

```
relations(id, from_ref, to_ref, from_kind, to_kind, type, confidence,
          justification, source, status, model, created_at)
  from_kind/to_kind ∈ 'node' | 'object'
  source            ∈ 'toe' | 'derived' | 'manual'
  status            ∈ 'proposed' | 'confirmed' | 'rejected'
  UNIQUE (from_ref, to_ref, type)
```

The tempting move is to add `'row'` to `from_kind`/`to_kind` and call the problem
solved. **Do not.** The two edge kinds have incompatible truth conditions:

| | structural join | semantic relation |
| --- | --- | --- |
| example | invoice **→** its customer | this customer **is-a** node in the taxonomy |
| authored by | the person entering data | an agent, a classifier, a curator |
| may be wrong | no — it is a constraint | yes — that is what `confidence` is for |
| may be `proposed` | no | yes, and usually starts there |
| cardinality | declared in the schema | discovered |
| deleting the target | must be refused or cascaded | leaves a dangling proposal, which is fine |

A `status='proposed'` invoice-to-customer link is not a weaker fact; it is a
corrupt invoice. Putting both in one table means either the moderation workflow
can reject a foreign key, or the foreign key silently bypasses moderation. Both
are worse than two tables.

**Decision: two mechanisms, one registry.**

- **`rowRef` column kind** — the structural join. Lives in `schema_json`, stored
  in `table_rows.data`, validated on write.
- **`relations` extended with `'row'`** — the semantic edge, unchanged in
  character: agent-proposed, confidence-scored, moderated. This is how a business
  row becomes *visible in the cortex graph* rather than merely stored.

Both feed one `ent:` view. §6b's warning applies: `ent:` resolution and AgentKit's
tools must share one registry, because two disagreeing views of what exists is
worse than no `ent:` at all.

---

## 3. `rowRef` — the concrete shape

```ts
// shared/contracts/table.ts
columnKindSchema: add 'rowRef'

columnDefSchema: add
  refTable:   z.string().optional(),   // required when kind === 'rowRef'
  refDisplay: z.string().optional(),   // column key in the target used as the label
  onDelete:   z.enum(['restrict', 'setNull', 'cascade']).default('restrict'),
```

Stored value: the target `row_id` as a plain string. **Not** a `{table,row}` pair —
the target table is declared once in the schema, so putting it in every row
invites the two to disagree, and a join whose target is per-row is not a schema.

Four rules that have to be enforced server-side, not in the UI:

1. **`refTable` must exist and be visible to the writer.** A `rowRef` into a table
   the writer cannot read is an existence oracle: writes succeed for real ids and
   fail for invented ones, which enumerates a private table one guess at a time.
   The estate has paid for exactly this shape once already — `hidden_fees/13`
   records Bone's per-user DB selected by a uid parameter behind a static shared
   bearer, where `_validate_uid` checks path traversal and not authorization.
   Validate the *reference* against the caller's visibility, not the table's.
2. **`required: true` + `onDelete: 'restrict'`** is the default for anything
   invoice-shaped. Legal records do not get orphaned quietly.
3. **Cycles.** `rowRef` allows self-referencing tables (a party owning a party),
   which is correct and useful. Depth-bound the expansion at read time rather than
   forbidding the cycle.
4. **Cross-driver refs.** A `libsql` table may point at a `postgres` one. Either
   forbid it in v1 or state plainly that referential integrity is not enforced
   across drivers. Silence here becomes a data-loss story later.

**Query surface.** `ListRowsQuery` gains an `expand: string[]` of `rowRef` column
keys, resolved one level, with a hard cap. `AggregateQuery` gains the ability to
group by `expand.<col>.<targetCol>` — that is the actual "join" in the OLAP sense
and it is what makes Superset-style questions answerable inside KEAP at all.
Declare it in `TableCapabilities` (`joins: boolean`) so a driver that cannot do it
renders a UI without the option, per the contract's existing pillar.

**Face UI.** A `rowRef` cell is a picker over the target table filtered by
`refDisplay`, an expandable chip when populated, and a back-reference panel on the
target row ("3 invoices reference this customer"). The back-reference needs an
index — `table_rows` is keyed `(table_id, row_id)` with the payload in a JSON
blob, so finding rows *pointing at* a given id is a full scan today. Add a
generated-column index per `rowRef` column, or a narrow `table_row_refs` mirror
maintained on write. **Decide this before the first load, not after** — retrofitting
an index over rows already written is a migration; adding it now is a DDL line.

---

## 4. What goes into DataTables, and what does not

The operator's stated payload: tax, contact, invoicing and delivery details;
end users (`nos-tenant-owner`). The split follows the estate's existing boundary
rule rather than convenience.

| data | home | why |
| --- | --- | --- |
| parties, addresses, tax identities, contact points | **DataTables** | this is the entity registry; it is what `ent:` resolves against |
| tenant owners and their attributes | **DataTables**, keyed to the Authentik subject | identity stays in Authentik; the *attributes* are entity data |
| invoices as accounting records, payments, ledger | **Firefly III** | double-entry belongs in a ledger, not a row store |
| analytics over any of it | **Superset** | already live |
| tickets and customer correspondence | **FreeScout** | already live |

**Two corrections to that plan, both worth knowing before you start typing.**

- **There is no CRM in the estate.** ERPNext is `install_erpnext: false`, marked
  EXPERIMENTAL / NON-WORKING, hard-blocked at role load behind
  `erpnext_experimental_override`, and excluded from the all-on profile. Anything
  routed "to the CRM" today has nowhere to land. Either DataTables holds it for
  now — which is defensible, since the entity registry is genuinely the right home
  for parties and contacts — or a CRM decision gets made explicitly.
- **Firefly III is `install_firefly: false`.** It is a working role, so this is a
  toggle and a converge, not a project — but invoicing data has no destination
  until it is on.

---

## 5. "Co nejobecněji" — do not invent the schema

The requirement that this generalise beyond one startup is the hardest part of the
task, and the failure mode is specific: a schema fitted to the operator's own
invoices that cannot represent a customer in another country.

Do not design party/address/tax structures from first principles. Adopt the
European e-invoicing semantic model (**EN 16931**, with **Peppol BIS Billing 3.0**
as its widely-used CIUS, and **ISDOC** as the Czech format) as the vocabulary for
seller, buyer, delivery party, tax scheme, tax registration, postal address and
payment means. Two reasons beyond generality: it is EU-native, which matches the
estate's EU-residency doctrine; and it is what any counterparty's system already
speaks, so the interoperability is inherited rather than built.

Concretely, that suggests roughly this table set — **general first, business
second**:

```
party           id, legal_name, trading_name, party_kind(person|org), country
tax_identity    party rowRef, scheme(VAT|local|other), value, valid_from/to
address         party rowRef, purpose(registered|delivery|billing), lines, city,
                postcode, country_subdivision, country
contact_point   party rowRef, kind(email|phone|web), value, role
tenant_owner    party rowRef, authentik_subject, tenant, tier
```

Every business-specific table then references `party` by `rowRef` rather than
re-declaring name-and-address columns. That is the difference between an entity
registry and five spreadsheets that each spell the customer's name slightly
differently.

Verify the exact EN 16931 field names against the standard before implementing —
the shape above is the argument, not a citation.

---

## 6. Making the external systems visible in the cortex

The operator's stated direction — *integration for the external systems, written
incrementally, visible in KEAP* — has an ownership rule already recorded in
`cortex-self-core.md` §7, and it points the opposite way from the obvious design:

> **nOS core lands each kind of data into the right system; cortex consolidates
> overnight. Cortex does not grow a connector per SaaS.**

So the integration is **not** "cortex reads Firefly". It is:

1. The external system stays authoritative for its own data.
2. A nightly consolidation job projects a **reference row** per external entity
   into DataTables — id, system, external key, display label, last-seen. Not a
   copy of the data; a handle.
3. `relations` (the semantic table, §2) links those handles to taxonomy nodes,
   which is what makes them appear in the graph and answerable by the corpus.
4. Queries that need the actual figures go to the owning system at read time.

This keeps one copy of every fact, which is the property that makes a knowledge
system trustworthy, and it keeps the connector count at one per system rather than
one per consumer.

---

## 7. Order of work

1. `rowRef` in the contract + validation + the back-reference index. **Decide the
   index before the first row is written.**
2. `expand` in `ListRowsQuery`; `joins` in `TableCapabilities`.
3. Face: picker, chip, back-reference panel.
4. The general party/address/tax tables, per §5.
5. Only then load real data.
6. `'row'` added to `relations.from_kind`/`to_kind`; `ent:` view over both
   mechanisms; drop `object_type_definitions`.
7. External-system handle projection, per §6.

Steps 1–4 are KEAP-side and produce a tag. Per
`cortex-s3-s4-workflow-set.md` §3, **the pin bump lands after the release lane's
third night** — a knowledge change needs a daemon restart, which needs a converge,
and the streak is measured under a fixed harness.
