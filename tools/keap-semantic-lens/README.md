# keap-semantic-lens — PoC tooling for the semantic-lens feature

Validates the difference-vector semantic axes on the live KEAP embedding corpus.
Design + results: `docs/plans/keap-semantic-lens.md`.

## Run the PoC
1. Dump node embeddings from the container (libSQL vector_extract):
   `docker cp tools/keap-semantic-lens/emb-dump.mjs iiab-keap-1:/app/emb-dump.mjs`
   `docker exec iiab-keap-1 node /app/emb-dump.mjs`  (writes /tmp/emb.jsonl in-container)
   `docker cp iiab-keap-1:/tmp/emb.jsonl <path>/emb.jsonl`
2. `python3 semantic-axes-poc.py`  (needs numpy + host Ollama at :11434 with
   nomic-embed-text; edit the EMB path if needed). Prints top/bottom nodes per axis
   + centrality — eyeball the axes are meaningful.

NEVER host `sqlite3` the live keap DB — emb-dump uses the libSQL driver in-container.
