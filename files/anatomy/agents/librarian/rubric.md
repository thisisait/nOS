# Librarian rubric

> ONE RUBRIC, FOUR CEREMONIES — and that is the constraint this file is
> written around. `outcomes.rubric_path` is per AGENT, while the librarian runs
> `brief-taxonomy`, `describe-taxonomy`, `judge-lint-queue` and (not yet live)
> the RAG recall. Until a rubric can be declared per ceremony, this one grades
> the SHARED contract first and applies exactly one skill section — whichever
> the task described.
>
> Rewritten 2026-08-16 after the first supervised AgentKit run. The previous
> file described only the recall ceremony and was marked contract-only, so the
> grader returned `failed` with *"rubric applies to 'Recall brief' … but agent
> performed 'taxonomy-brief'"*. The verdict was right and the measure was
> wrong: no taxonomy batch could ever have passed it.

## A. The shared contract — graded on every run

1. **The task, and only the task.** The batch the prompt described was
   attempted. Working a different skill, or widening the batch beyond the
   stated limit, is `failed` however good the output.
2. **Errors are reported verbatim.** Any non-2xx, refusal or partial write
   appears in the report with the server's own words. A run that hides a
   failure behind a summary is `failed` even if the rest succeeded — this is
   the property the whole audit trail rests on.
3. **No decisions.** The librarian surfaces and proposes; it never writes
   "operator should" or "I have therefore decided". Such a line is `failed`.
4. **Awaiting moderation is SUCCESS.** Every write path this agent has ends in
   a proposal a human approves. A report saying "N proposed, awaiting the
   moderator" has finished its job; grading that as incomplete would train the
   agent to escalate what is merely normal.
5. **The report reaches Wing** as `type=conductor_report`, `source=librarian`,
   under a `## Librarian report` heading, and the run ends with the
   `NOS_AGENT_EXIT:` line the runner reads. A report the agent only *printed*
   did not happen.
6. **Empty is an answer.** If the queue is genuinely empty, say so with the
   number that made it empty. Inventing work to look productive is `failed`.

## B. `brief-taxonomy` — the root taxonomy sweep

Applies when the task names the taxonomy-brief skill.

Each brief submitted MUST satisfy what the server will enforce anyway, so a
rejection is a drafting failure and not a surprise:

1. **English body** of 2-4 real paragraphs, blank-line separated, 300-12000
   characters. Captions and single paragraphs are rejected at the door.
2. **A real Czech translation** when given, 200-12000 characters — a
   translation of *this* brief, not a paraphrase of the node name.
3. **2-5 `[[node-id]]` links, mandatory**, every one resolving to a node that
   exists. Briefs carry the vazby; a brief with none is refused server-side.
4. **1-3 durable external links**, `http(s)` only, chosen for still being
   there in five years rather than for being first in a search.
5. **Built on the K1 description** the server supplied — a brief that ignores
   the node's own description is a generic essay about the title.

Batch discipline: one POST carrying every item, per-item errors reported
verbatim, and the `Summary` section stating batch size, proposed count, error
count and the remaining total. `needs_revision` when the briefs are sound but
the report omits a count; `failed` when a brief was submitted that the server
rejected for a rule listed above, because that rule was knowable first.

## C. `describe-taxonomy` — the K1 description pass

Applies when the task names the taxonomy-describe skill. Same batch discipline
as B. Descriptions are short by design: judged on whether each says what the
node *is* and how it differs from its siblings, not on length.

## D. `judge-lint-queue`

Applies when the task names the lint queue. Each judgement cites the specific
lint row it answers and states the reason in one sentence. A verdict without
its row reference is `failed` — an unattributable judgement cannot be reviewed.

## E. `Recall brief` — the RAG ceremony (NOT YET LIVE)

Retained verbatim from the 2026-05-17 contract. Applies once the runner lands
and the Qdrant corpus is non-empty; until then no task should name it.

- Report under heading `## Recall brief`.
- Three sub-sections, in order: `Query summary`, `Matches found`,
  `Decision relevance`.

Each bullet under `Matches found` MUST include:

1. **Source row** — wing.db row reference (events.id, remediation_items.id,
   etc.) the matched Qdrant point indexes.
2. **Similarity score** — Qdrant cosine similarity (0.0-1.0). Below the
   threshold default (0.75) means `needs_revision`.
3. **Verbatim excerpt** — 1-2 sentences from the matched source row that
   demonstrates the similarity to the current query.
4. **What's different** — explicit call-out of why the current case isn't
   identical (otherwise this is just "we already fixed it").

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

## Verdicts

- `satisfied` — section A holds and the applicable skill section holds.
- `needs_revision` — the work is sound but the report is incomplete: a missing
  count, an omitted section, a link that could be sharper.
- `failed` — a section A violation, or a submission rejected for a rule the
  agent could have checked before sending.
