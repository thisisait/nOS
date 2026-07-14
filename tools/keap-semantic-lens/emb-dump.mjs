import Database from 'libsql';
import { writeFileSync } from 'node:fs';
const db = new Database('/data/keap.db', { readonly: true });
const rows = db.prepare("SELECT ref_id, vector_extract(vector) AS v FROM embeddings WHERE kind='taxonomy'").all();
const out = rows.map(r => JSON.stringify({ id: r.ref_id, v: JSON.parse(r.v) })).join('\n');
writeFileSync('/tmp/emb.jsonl', out);
console.log('dumped', rows.length, 'embeddings');
