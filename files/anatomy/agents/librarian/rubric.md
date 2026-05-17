# Librarian report rubric

> Contract-only (2026-05-17). The grader rubric below applies once the
> runner lands + Qdrant corpus is non-empty.

## Structure

- Report under heading `## Recall brief`.
- Three sub-sections, in order: `Query summary`, `Matches found`,
  `Decision relevance`.

## Matches contract

Each bullet under `Matches found` MUST include:

1. **Source row** — wing.db row reference (events.id, remediation_items.id,
   etc.) the matched Qdrant point indexes.
2. **Similarity score** — Qdrant cosine similarity (0.0-1.0). Below
   the threshold default (0.75) means `needs_revision`.
3. **Verbatim excerpt** — 1-2 sentences from the matched source row
   that demonstrates the similarity to the current query.
4. **What's different** — explicit call-out of why the current case
   isn't identical (otherwise this is just "we already fixed it").

## No-recommendation check

- The report MUST NOT include "operator should X" / "recommend Y"
  language. Librarian surfaces context, doesn't decide. Such lines
  return `failed`.

## Empty-corpus / no-match case

If Qdrant returns zero matches above threshold, the report is exactly:

```
## Recall brief

### Query summary
Query: <verbatim>. Threshold: 0.75. Matches: 0.

### Matches found
_None above similarity threshold._

### Decision relevance
No prior context available — operator decides without precedent.
```
