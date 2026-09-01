# Qdrant — for agents

**What you may assume:** nothing is authoritative here. Qdrant holds DERIVED
vectors; the canonical row is in Postgres, wing.db or the security queue. A
disagreement between Qdrant and a canonical store is Qdrant being stale, never
the other way round.

**Ingestion goes through Bone.** Bone is the redaction point for the GDPR
record; an agent writing points directly bypasses it and puts unredacted prompt
context into a store nobody audits.

**Absence is not an answer.** A similarity query returning nothing means "no
near neighbour in what has been embedded so far", not "no such thing exists".
Report the empty result as an empty result.

**Liveness** is `GET /healthz` on `127.0.0.1:6333`, unauthenticated. The
collection endpoints need the API key.
