<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * The keys handlers WRITE onto rows, named in one place — the missing contract.
 *
 * A cortex row carries two kinds of key and, until 2026-08-12, nothing said so:
 * the entity's own facts (`id`, `name`, `summary`, `resolvedName`, …) and the
 * marks a handler leaves while producing it (`ns`, `mappedFrom`, `rankSignal`,
 * the `classify*` family). Both lived in one flat keyspace, and the first
 * consumer to treat them alike proved why that needs a name: `filter
 * where=tax` kept 5/5 rows — verified live — because every row carried
 * `ns: "tax"`, a value the HANDLER wrote, matched by a predicate the CALLER
 * thought was about their data. The filter was matching the pipeline's own
 * handwriting.
 *
 * The contract, stated once: a free-text predicate over "the row" means the
 * row's DATA. Provenance is addressable — a stage that wants to select on an
 * assignment or a namespace needs that expressed as AST structure the
 * validator can see (the same rule FilterHandler's header applies to `where`
 * generally), not smuggled through a substring that happens to collide.
 *
 * `classifiedAs` / `classifiedAsName` sit in this list deliberately:
 * FilterHandler::identifies() already records that filtering BY an assignment
 * is a decision to take openly (add the key there, with review), and letting
 * `where` reach the assignment as a substring would be that decision taken by
 * accident.
 *
 * ADDITIVE MAINTENANCE RULE: a handler that starts writing a new mark onto
 * rows adds it here in the same commit. An unlisted provenance key is exactly
 * the silent collision this class exists to end.
 */
final class CortexRowProvenance
{
    /** @var list<string> */
    public const KEYS = [
        'ns',              // every handler: which namespace produced the row
        'mappedFrom',      // map: the parent the child was projected from
        'rankSignal',      // rank: the score, or null when unscored
        'rankBy',          // rank: the signal the ordering was made from
        'classifiedAs',    // classify: assignment id
        'classifiedAsName',
        'classifyScore',
        'classifyBy',
        'classifyNote',
        'classifyLegs',
    ];

    public static function isProvenance(string $key): bool
    {
        return in_array($key, self::KEYS, true);
    }
}
