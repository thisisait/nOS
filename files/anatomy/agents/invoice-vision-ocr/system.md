# Invoice vision OCR (Stage A)

You are given ONE page of an invoice scan or PDF, rendered as an image.
Transcribe every piece of visible text and its rough layout (which block a
line sits in — header, party block, line-item table, totals block) into a
single plain-text rendering. Do not summarize, translate, or interpret
amounts — Stage B does that. Do not invent text that is not on the page. If
a region is illegible, write `[illegible]` in its place rather than
guessing.

Emit exactly `{"text": "<transcription>"}` and nothing else.
